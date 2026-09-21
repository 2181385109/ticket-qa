# ADR-006: SLA 超时按闭区间判定,重复触发靠数据库条件更新 + 永久标记防住

## 背景

P0 / P1 / P2 的响应时限是 15 / 60 / 240 分钟,计时起点是创建时刻,超时仍未进入 `PROCESSING`
就自动升级到 `ESCALATED` 并发 MQ。定时任务每 30 秒扫一次。三个问题必须定死:

1. "恰好等于时限"算不算超时——这是边界值用例的依据,不定死用例没法写。
2. 同一工单绝不能被升级两次——扫描是周期性的,升级后的工单如果又回到 ASSIGNED,
   下一轮扫描还会看到它;多实例部署时两个实例可能同时扫到同一张。
3. "现在"从哪来——Java 的 `LocalDateTime.now()` 和 MySQL 的 `NOW()` 可能不在一个时区,
   测试也没法把它钉死。

## 选项

### 边界

- **方案 A:闭区间,`sla_deadline <= now` 算超时** ← 采用(规格指定)
  elapsed ≥ limit 即超时。恰好 15 分钟 00 秒 000 毫秒的 P0 工单会被升级。
- **方案 B:开区间,`sla_deadline < now`**
  恰好等于不算。差别只在毫秒级的边界上,但用例断言必须选一边。

### 防重复触发

- **方案 A:扫描前先加分布式锁,锁内 SELECT 再 UPDATE**
  代价:锁只防"并发",不防"顺序重复"——这一轮升级了,工单被组长改派回 ASSIGNED,
  下一轮扫描又命中,又升级一次。而且 Redis 不可用时要么扫描停摆,要么锁失效。

- **方案 B:条件更新 + 永久标记** ← 采用
  做法:
  ```sql
  UPDATE ticket SET status='ESCALATED', escalated_at=?
   WHERE id=? AND status IN ('PENDING','ASSIGNED') AND escalated_at IS NULL
  ```
  受影响行数为 1 才写审计、发事件;为 0 说明已经被处理(另一实例、上一轮、或人工刚好
  流转走了),直接跳过。`escalated_at` 写上后**永不清空**,扫描 SQL 里
  `escalated_at IS NULL` 保证一张工单只会被自动升级一次——哪怕它之后回到 ASSIGNED。
  代价:一张被升级过又回到 ASSIGNED 的工单不会再被自动升级;需要人盯。

- **方案 C:升级时把 `sla_deadline` 往后推,或清空**
  代价:把"截止时间"这个事实改掉了,审计和统计失去原始依据;而且改成什么值都是拍脑袋。

### Redis 锁的角色

在方案 B 之上,`SlaScanner` 还是用了 Redis `SET NX PX` 加了一把扫描锁。它的作用是
**减少多实例同时扫描时的无谓冲突**(两个实例扫到同一批,一个全部成功、一个全部受影响 0 行,
白做一次查询),不是正确性保证。所以 Redis 不可用时**fail-open**:打 WARN、
`sla_scan_lock_unavailable_total` +1、照常扫描。正确性由数据库条件更新兜底。

### 时间来源

- **方案 A:SQL 里用 `NOW()`**
  代价:时区由 MySQL 连接决定;测试没法把"现在"钉死,边界值用例只能靠等真实时间。
- **方案 B:应用层注入 `java.time.Clock`,`now` 作为参数传进 SQL** ← 采用
  做法:`ClockConfig` 按 `app.time-zone` 建一个 `Clock` Bean,所有 `LocalDateTime.now(clock)`。
  单测用 `Clock.fixed(...)` 把时间钉在 `sla_deadline` 那一毫秒,验证闭区间。
  代价:比直接 `LocalDateTime.now()` 多注入一个东西;团队要养成不直接调 `now()` 的习惯。

另外:`sla_deadline` 在**创建时**算好存成列,`created_at` 显式设为 LLM 调用之前那个 `now`,
保证 `sla_deadline == created_at + limit` 这个不变量(索引理由见 ADR-005)。

## 决定

- 闭区间:`sla_deadline <= now`。恰好等于即超时。
- 超时判定只看 `PENDING` / `ASSIGNED`;`PROCESSING` 及之后的状态视为已响应;`ESCALATED`
  已升级。
- 防重复:条件 UPDATE + `escalated_at` 永久标记,每张工单一个独立事务
  (`SlaEscalationService.escalate` 是 `@Transactional`,`SlaScanner` 逐张调用)。
- Redis 扫描锁只做优化,fail-open。
- `Clock` 注入,时区 `Asia/Shanghai` 在 `application.yml` 显式声明,MySQL 连接串也带
  `serverTimezone=Asia/Shanghai`,容器 `TZ=Asia/Shanghai`——三处一致。
- 提供 `POST /api/admin/sla/scan` 手动触发一轮,测试不用等 30 秒定时器。

## 后果

- 接受:被升级过的工单不会再被自动升级。这是规格"同一工单不能被升级两次"的字面实现,
  也是最保守的解释。如果业务想要"每次回到未响应状态都重新计时",需要把 `escalated_at`
  改成计数或在改派时清空——那是另一条 ADR。
- 接受:扫描周期 30 秒意味着最坏延迟 30 秒:P0 工单可能在超时后第 29 秒才被升级。
  边界值用例断言的是"扫描时刻判定正确",不是"超时瞬间被升级"。
- 接受:每张工单一个事务,100 张就是 100 个事务。比一个大事务慢,但一张失败不拖累其他。
- 什么场景下会是错的:每分钟成千上万张工单超时——逐张事务就太慢了,要改成批量 UPDATE
  `WHERE id IN (...)` 再按受影响行数反查。

> **2026-09-21 更新**:条件更新的 WHERE 增加 `status = 读到的值 AND version = 读到的版本`(ADR-017)。原来的
> `status IN ('PENDING','ASSIGNED')` 只保证不重复升级,不保证审计 from 正确——扫描读到 PENDING、升级前被抢成 ASSIGNED 时
> UPDATE 照样命中而审计记成 `PENDING→ESCALATED`。现在这种情况影响 0 行、下一轮重扫。`SlaOverdueQueryH2Test.staleFromStatusDoesNotEscalate` 复现了它。

## 常见质疑与回应

**Q:为什么闭区间?开区间不是更直觉——"超过"才叫超时?**
> 规格指定的,但我能说明它合理:SLA 是承诺"15 分钟内响应",到第 15 分钟整还没响应就是
> 没兑现承诺,不需要再多等一毫秒。更重要的是必须只选一边并写进 ADR,因为边界值用例
> 要断言"恰好等于"这一个点的行为,两边都行的话用例就没有依据了。

**Q:防重复为什么不用分布式锁?**
> 锁解决的是"两个实例同时扫"的并发问题,解决不了"这一轮升级了、改派回去、下一轮又升级"
> 的顺序重复问题。条件更新 + escalated_at 标记两个都解决:并发时只有一个 UPDATE 能影响
> 到行,顺序重复时 `escalated_at IS NULL` 直接把它排除在扫描之外。我也加了 Redis 锁,但
> 它只是减少多实例白做一次查询的优化,Redis 挂了扫描照常跑,正确性不靠它。

**Q:Redis 挂了你还继续扫,不怕两个实例重复升级?**
> 不怕,因为条件更新是原子的:两个实例对同一行发 UPDATE,InnoDB 行锁保证一个先执行、
> 把 status 改成 ESCALATED,另一个再执行时 WHERE 条件不满足、受影响 0 行。第二个实例看到
> 0 行就跳过,不写审计不发事件。所以最坏情况是多做一次无效 UPDATE,不会有第二条审计。

**Q:escalated_at 永不清空,业务上合理吗?**
> 这是按规格字面意思做的默认选择,"不能被升级两次"的字面意思。业务上有争议:一张单被升级、
> 组长改派回去、坐席又不响应,要不要再升级一次?我认为要的话应该是人工决定,不是定时
> 任务再来一次——因为第二次超时的责任人已经变了。如果业务要自动重计时,改派时清空
> escalated_at 就行,一行代码,但要另开一条 ADR 记录为什么改。

**Q:为什么不用 MySQL 的 NOW(),非要传参数?**
> 两个理由。一是可测:`Clock.fixed()` 能把时间钉在截止时刻那一毫秒,直接验证闭区间;
> 用 NOW() 只能等真实时间走到那一刻。二是一致:同一轮扫描里所有工单用同一个 now,
> 审计备注、事件时间戳、UPDATE 条件全部一致;NOW() 在事务里虽然也是同一个值,但和应用层
> 打的日志时间可能差几毫秒,排查时会困惑。
