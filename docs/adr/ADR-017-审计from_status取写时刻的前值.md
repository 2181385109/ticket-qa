# ADR-017: 审计 `from_status` 必须是 UPDATE 实际影响的那一行的前值,不能用内存快照

## 背景

压测([记录](../findings/20260920-压测-审计日志记录未发生的状态转换.md))发现同一张工单在
`ticket_audit_log` 里出现 12 条 `PENDING→ASSIGNED`,而库里的状态只从 PENDING 变成 ASSIGNED 过一次:
后 11 次 UPDATE 执行时行上已经是 ASSIGNED,真实发生的是 `ASSIGNED→ASSIGNED`(换人),审计却记成
`PENDING→ASSIGNED`。持锁演示里 5 条审计的 `from` 是 42 秒前的旧值,组长的指派在审计里连一行都看不出。

产生路径:`TicketStateMachine.transit` 第 43 行 `from = ticket.getStatus()` 取自 SELECT 时刻的内存对象;
`updateById` 等锁多久、期间行被改成什么,都不会反映进来。这不是 MySQL 的脏读(隔离级别没问题),
是应用层把"读时刻的状态"当成了"写时刻的状态"。

审计表的用途是数据一致性校验(CLAUDE.md §5.8):从审计能还原状态历史。它一旦撒谎,
状态迁移法的事后校验会全部通过——校验器被喂了假数据,而且正好把重复分配(KI-008)藏起来。
范围不止 grab:`transit()`、`assign()`、`escalate()` 都是"SELECT → 内存判断 → UPDATE → 用内存里的 from 写审计"。

## 选项

- **方案 A:让 UPDATE 只在"前值等于我以为的前值"时生效,审计的 from 就是 WHERE 里断言过的值** ← 采用
  做法:两条路径。
  ① 抢单 / SLA 升级——业务谓词直接写进 WHERE:`status = 'PENDING'`(grab)、`status = #{from}`(escalate);
  ② 状态机流转 / 改派 / 修改——乐观锁 `version = ?` 写进 WHERE(ADR-016 方案 B)。
  两者都满足同一条推理:UPDATE 是当前读,受影响行数为 1 ⇔ 在持有行锁的那一刻谓词为真 ⇔ 写之前那一行
  的 status(或整行)就是我快照里的样子。所以审计只在 `affected == 1` 之后写,写的 from 就是快照里的
  status——此时它不再是"快照",是被数据库在锁下验证过的事实。受影响 0 行 → 抛异常 → 事务回滚 → 没有审计。
  代价:并发失败方拿到 409,需要重读重试;没有"回读一次拿真值再写审计"的容错(见方案 B 为什么不选)。

- 方案 B:UPDATE 之后 `SELECT ... FOR UPDATE` 回读前值,再写审计
  做法:先 `SELECT status FROM ticket WHERE id=? FOR UPDATE`(锁定读拿到真值),再 UPDATE,再用真值写审计。
  代价:多一次往返;更重要的是它让"抢单"的语义变成"谁拿到锁谁赢,不管前值是什么"——
  ASSIGNED 的单会被第二个人改成 ASSIGNED 并记一条真实的 `ASSIGNED→ASSIGNED`,审计对了但业务错了
  (重复分配换了个更诚实的写法)。审计正确不能以业务正确为代价。

- 方案 C:审计表加 `expected_from` / `actual_from` 两列,校验器事后比对
  做法:写审计时同时记"我以为的前值"和"触发器 / 回读拿到的真值"。
  代价:触发器或回读的成本;更根本的问题是它把一个应该在写入时拦住的错误变成了事后发现——
  审计的价值在于它是可信的事实,不是"可能对、需要再校验"的线索。

- 方案 D:审计 from 用 MySQL 触发器在 `BEFORE UPDATE` 里取 `OLD.status` 写入
  做法:数据库层保证 from 一定是行的旧值。
  代价:审计逻辑分裂到 DDL 里,operator / source / remark 这些应用层信息触发器拿不到,要靠会话变量传递;
  H2 切片测试跑不了触发器;并且它同样只解决审计不解决重复分配。

## 决定

方案 A。具体改动:

| 路径 | 改前 | 改后 | 受影响 0 行时 |
|---|---|---|---|
| `grab` | `updateById` + 内存 from | `grabIfPending(... WHERE status='PENDING' AND version=?)`,from 固定为 PENDING | 40901,不写审计 |
| `transit` / `assign` / `update` | `updateById` | `updateOrConflict` → `updateById` 被乐观锁拦截器改写为 `WHERE id=? AND version=?` | 40903,不写审计 |
| `SlaEscalationService.escalate` | `escalateIfStillUnresponded(id, now)` WHERE `status IN (PENDING, ASSIGNED)` | 增加 `AND status = #{from} AND version = #{version}` | skipped +1,留给下一轮扫描重新读 |

SLA 那条值得单独说:改前 SELECT 读到 PENDING、UPDATE 前被人抢成 ASSIGNED,UPDATE 仍然成功(ASSIGNED 也在
IN 列表里),审计却记 `PENDING→ESCALATED`。改后这种情况影响 0 行,`escalated_at` 仍为空,下一轮(30 s 后)
重新读到 ASSIGNED 再升级,审计记的就是真实的 `ASSIGNED→ESCALATED`。H2 切片测试
`SlaOverdueQueryH2Test.staleFromStatusDoesNotEscalate` 在 SQL 层复现了这个场景。

配套的反向断言(`tests/api/framework/audit.py`):同一 ticket_id 的审计按 id 排序,第 k 行 `to_status`
必须等于第 k+1 行 `from_status`,首行 from 为空,末行 to 等于 `ticket.status`,每条边在迁移表里。
修复前压测留下的数据上它必然失败,修复后全库扫描 0 张断裂。压测取证脚本 `grab_evidence.py` 的 Q4 也是这条。

## 后果

- 接受:并发下"晚到的一方"得到 409 而不是被静默合并。这正是想要的——审计里不再有没发生过的转换。
- 接受:SLA 升级在"扫描与升级之间被人流转"时延后最多一个扫描周期(30 s);skipped 计数会增加,
  它和"已被另一实例升级"共用一个计数,分不开。若要分开,需要再查一次库,不值得。
- 接受:审计的 from 仍然由应用层写入,不是数据库层"强制"的;保证来自"只有 affected==1 才写"这个
  代码约定,`AuditLogService.record` 的 `MANDATORY` 传播保证它至少和 UPDATE 在同一个事务里。
- 什么场景下这个选择会是错的:如果某条写路径需要"无论前值是什么都写入"(比如管理员强制重置状态),
  那条路径就不能用 version 拦截——它要么用 `FOR UPDATE` 回读真值写审计(方案 B),要么 from 记 null 并在
  source 里标明"强制"。本项目没有这种路径。

## 常见质疑与回应

**Q:审计 from 错了,直接在写审计前再 SELECT 一次不就行了?**
> 再 SELECT 一次拿到的还是快照,除非 FOR UPDATE;而 FOR UPDATE 回读虽然能拿到真值,但它让抢单变成
> "谁拿到锁谁赢",ASSIGNED 的单照样被第二个人改掉,只是审计诚实地记了 `ASSIGNED→ASSIGNED`。
> 审计对了,业务还是错的。正确的顺序是:先让数据库在锁下验证"前值确实是我以为的",验证通过再写审计,
> 验证失败就回滚。这样审计的 from 不是"读到的",是"被验证过的"。

**Q:那 from 到底是从哪来的?你还是用了内存里的值。**
> 值确实来自内存快照,但它的可信度来自 UPDATE 的受影响行数。UPDATE 是当前读:InnoDB 拿到行锁后在
> 最新已提交版本上求值 `status='PENDING' AND version=?`。受影响 1 行意味着在那一刻、那把锁下,
> 行的 status 就是 PENDING、version 就是我读到的——所以快照和真值相等,用哪个都一样。
> 受影响 0 行意味着快照过期,此时我不写审计。这是"用受影响行数把快照升级成事实"。

**Q:为什么不用数据库触发器保证 from?那才是真正的强制。**
> 触发器能拿到 `OLD.status`,但拿不到 operator、source、remark、traceId 这些应用层信息,
> 要靠会话变量绕;审计逻辑一半在 Java 一半在 DDL,读代码的人要两头看;H2 切片测试跑不了 MySQL 触发器。
> 而且触发器只修审计不修业务——重复分配照样发生。我更愿意用一个机制同时解决两个问题。

**Q:SLA 升级为什么要加 version?它本来就有条件更新。**
> 原来的条件是 `status IN ('PENDING','ASSIGNED')`,它保证"不重复升级",但不保证"审计的 from 对"——
> 扫描读到 PENDING,升级前被抢成 ASSIGNED,UPDATE 照样命中(ASSIGNED 也在列表里),审计却写 `PENDING→ESCALATED`。
> 加上 `status = 读到的值 AND version = 读到的版本`,这种情况变成 0 行、下一轮重扫。代价是延后 30 秒,
> 换来审计不撒谎。我在 H2 上用两条 SQL 复现了这个场景,单测里能看到。

**Q:怎么证明现在的审计是对的?你不可能人工看几万行。**
> 反向断言:按 id 排序后第 k 行的 to 必须等于第 k+1 行的 from,末行 to 等于当前状态,每条边都在迁移表里。
> 这条断言在修复前的数据上必然失败(12 条 PENDING→ASSIGNED 连不起来),修复后全库 0 张断裂。
> 它在接口自动化里是一个 fixture 级的检查(每个并发用例都跑),也是压测取证脚本的第四条 SQL。
> 正向断言"有没有那一行"发现不了 KI-009,反向断言才能。
