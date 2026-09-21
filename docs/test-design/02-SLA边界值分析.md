# 02 · SLA 边界值分析

方法:**边界值分析**(主)+ **场景法**(扫描 / 升级 / 防重复流程)。

为什么用边界值:SLA 是"时间 ≥ 阈值"的判定,输入域有序、规格明确给了闭区间(CLAUDE.md §5.3、ADR-006)。
这种判定的缺陷几乎只出现在边界上——`<` 写成 `<=`、时区差 8 小时、跨天日期比较——所以用例要集中在边界点两侧,
而不是随机取几个"明显超时"的点。

## 1. 两个可测的量

SLA 由两步组成,测试分别打:

| 量 | 在哪里算 | 输入 | 测什么 |
|---|---|---|---|
| ① 截止时间 `sla_deadline = created_at + 时限(priority)` | `TicketService.create` | 创建时刻(Clock)、优先级 | 起点是否正确、时长是否按表、跨天 / 跨时区 |
| ② 超时判定 `sla_deadline <= now` | `TicketMapper.selectSlaOverdueIds`(SQL) | now(Clock)、状态、escalated_at、deleted | 闭区间、过滤条件、排序 / limit |

两个量分开测的原因:① 是 Java 逻辑,Mockito 能测;② 是 SQL,必须在数据库上跑(ADR-013)。

## 2. 量 ①:截止时间计算

### 2.1 时长按优先级——等价类(三个有效类)

| 优先级 | 时限 | 用例 |
|---|---|---|
| P0 | 15 min | `SlaDeadlineTest.deadlineByPriority[P0]`;接口 `test_sla_deadline_equals_created_plus_limit[P0]` |
| P1 | 60 min | 同上 [P1] |
| P2 | 240 min | 同上 [P2] |

接口层的优先级由挡板关键词"钉住"(技术故障词 → P0,退款词 → P1,兜底 → P2),响应里 `slaDeadline - createdAt` 精确等于时限。

### 2.2 起点是创建时刻,不是 LLM 返回时刻

LLM 调用最多 3 秒,如果起点取在调用之后,截止时间会晚 3 秒。用例:`deadlineAnchoredOnCreationInstant`——
用固定 Clock,断言落库的 `createdAt == NOW` 且 `slaDeadline == createdAt + 15min`。
降级分类给出的优先级同样决定时限:`degradedPriorityStillDrivesDeadline`。

### 2.3 跨天 / 跨月——日期边界

| 创建时刻 | 优先级 | 期望截止 | 用例 |
|---|---|---|---|
| 2026-09-20 23:50:00 | P0 | 2026-09-21 00:05:00 | `crossesMidnight` |
| 2026-09-30 22:30:00 | P2 | 2026-10-01 02:30:00 | `crossesMonthBoundary` |

断言截止日期 > 创建日期,防止"只比时分不比日期"的错误。

### 2.4 跨时区——同一瞬间、不同墙钟

`Clock` 是注入的(ADR-006),用两个 Clock 指向**同一个 Instant**、不同时区:

| Clock 时区 | createdAt(墙钟) | slaDeadline | 断言 |
|---|---|---|---|
| Asia/Shanghai | 2026-09-21 00:00:00 | 00:15:00 | 时长 15 min |
| UTC | 2026-09-20 16:00:00 | 16:15:00 | 时长 15 min |

两者墙钟差 8 小时、日期不同,但 `deadline - created` 相等,且两个截止时刻换算成 Instant 是同一个物理瞬间。
用例:`sameInstantDifferentZones`。这条防的是"时区在配置里显式声明"(CLAUDE.md §6)被谁改成 `LocalDateTime.now()` 后的静默漂移。

## 3. 量 ②:超时判定——闭区间边界(真实 SQL,H2 切片)

规格:恰好等于时限即算超时。SQL:`sla_deadline <= #{now}`。以截止时刻 D 为中心取五个点:

| now | 相对 D | 期望 | 用例(`SlaOverdueQueryH2Test.ClosedInterval`) |
|---|---|---|---|
| D − 1s | 界内 | 未超时 | `oneSecondBeforeIsNotOverdue` |
| D − 1ms | 界内 −1 | 未超时 | `oneMillisecondBeforeIsNotOverdue` |
| **D** | **边界** | **超时** | `exactlyAtDeadlineIsOverdue` ← 闭区间的核心用例 |
| D + 1ms | 界外 +1 | 超时 | `oneMillisecondAfterIsOverdue` |
| D + 1s | 界外 | 超时 | `oneSecondAfterIsOverdue` |

精度到毫秒:列类型 `DATETIME(3)`,±1ms 是它能表达的最小步长;如果实现改成秒级比较,`D − 1ms` 会误判为超时,这条用例会红。

跨天:D = 2026-09-20 23:59:59.999,now = 09-21 00:00:00.000 → 超时;now = 09-20 23:59:59.998 → 未超时(`crossesMidnight`)。

### 3.1 过滤条件——等价类

| 条件 | 有效类(应扫到) | 无效类(不应扫到) | 用例 |
|---|---|---|---|
| status | PENDING、ASSIGNED | PROCESSING、WAIT_CONFIRM、CLOSED、ESCALATED | `unrespondedStatusesAreScanned` / `respondedStatusesAreIgnored`(各参数化) |
| escalated_at | NULL | 非 NULL(即使又回到 ASSIGNED) | `alreadyEscalatedIsIgnored` |
| deleted | 0 | 1 | `deletedIsIgnored` |
| 排序 / limit | 按 sla_deadline 升序,受 limit 截断 | — | `orderedByDeadlineAndLimited` |

### 3.2 接口层的边界(真 MySQL,精度受限)

接口测试控制不了服务的 now,只能改 `sla_deadline` 列(用数据库的 `NOW(3)`,避免宿主与容器时钟不一致):

| sla_deadline | 扫描结果 | 用例(`test_sla.py`) |
|---|---|---|
| now − 1s | 升级 | `test_overdue_pending_is_escalated`、`test_overdue_assigned_is_escalated` |
| now + 3s | 不升级;3.5 秒后再扫 → 升级 | `test_deadline_in_near_future`(超时判定随时间单调) |
| now − 60s 但状态 PROCESSING / WAIT_CONFIRM / CLOSED | 不升级 | `test_responded_ticket_not_escalated` |

"恰好等于"在这一层碰不到,由 §3 的 H2 用例负责——两层分工,不重复也不留空。

## 4. 升级动作与防重复——场景法

规格:同一工单不能被升级两次。实现是条件 UPDATE(ADR-006):
`UPDATE ticket SET status='ESCALATED', escalated_at=now WHERE id=? AND status IN ('PENDING','ASSIGNED') AND escalated_at IS NULL`。

| 场景 | 步骤 | 期望 | 用例 |
|---|---|---|---|
| S1 首次升级 | 条件更新影响 1 行 | 审计 source=SCHEDULER、operator 为空、from=原状态;STATUS_CHANGED + SLA_ESCALATED 两条事件;`sla_escalated_total`+1 | 单测 `escalatesWhenConditionalUpdateHits`;接口 `test_overdue_pending_is_escalated` |
| S2 已被处理 | 影响 0 行 | `sla_escalation_skipped_total`+1,不审计不发事件 | 单测 `skipsWhenConditionalUpdateMisses` |
| S3 连扫两轮 | 第二轮 0 行 | 只一条 SCHEDULER 审计 | 单测 `secondCallOnSameTicketIsNoOp`;H2 `escalatesOnceOnly`;接口 `test_second_scan_is_noop` |
| S4 升级后指派回 ASSIGNED、截止仍在过去 | 再扫 | 不再升级(`escalated_at` 永久标记) | H2 `reassignedAfterEscalationIsNotEscalatedAgain`;接口 `test_reassigned_after_escalation_not_escalated_again` |
| S5 扫描后、升级前人工推进到 PROCESSING | 条件更新 | 0 行,不覆盖人工操作 | H2 `manualProgressWinsTheRace` |
| S6 批量 | 三张超时单一轮 | 全部升级,各一条审计 | 接口 `test_batch_escalation` |
| S7 工单被物理删除 | selectById 为 null | 返回 false | 单测 `missingTicketReturnsFalse` |

## 5. 扫描器——场景法(锁与容错)

| 场景 | 期望 | 用例(`SlaScannerTest`) |
|---|---|---|
| 拿到锁,扫到 N 张 | now 来自 Clock、batch 来自配置、逐张升级、最后释放锁 | `scansWithLockAndClockNow` |
| 没有超时单 | 返回 0,不调升级 | `nothingOverdue` |
| 锁被别的实例持有 | 本轮跳过,不查库 | `skipsWhenLockHeldElsewhere` |
| Redis 不可用 | fail-open 照常扫,`sla_scan_lock_unavailable_total`+1,不释放锁 | `failsOpenWhenRedisDown` |
| 某一张升级抛异常 | 其他继续,返回值只计成功 | `oneFailureDoesNotStopTheBatch` |
| 查库抛异常 | 定时方法吞掉异常,finally 仍释放锁 | `scheduledScanSwallowsExceptions` |
| 扫描接口权限 | 只有 ADMIN;LEADER/AGENT 40302;匿名 40101 | 接口 `test_scan_permission` |
