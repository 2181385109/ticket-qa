# 用例清单(test-inventory)

统计口径:2026-09-21 本地全跑(修复阶段后)。**单测 330 次执行(含参数化展开),接口 + 安全 312 次执行**,
全部通过,3 条 xfail(strict,已知问题 KI-001 / KI-002),0 skip。修复阶段新增的用例在 §5,设计文档 08。
> 全库审计扫描 `test_no_broken_chain_in_database` 原来在空库上条件 skip(2026-09-21 冷启动后的那次全跑就是 1 skipped);现在用例先造三张不同终态的工单再扫,任何环境都实跑。套件里不再有 skip——唯一保留的条件 skip 是 `fault` 用例在没配 `DOCKER_COMPOSE_CMD` 的环境整体跳过(conftest,原因写在 skip 消息里),CI 与本地都配了。

列说明:**层** UT=JUnit 单测(`service/src/test/java`)、API=pytest 接口(`tests/api`)、SEC=pytest 安全(`tests/security`)、PERF=JMeter 模板(`tests/perf`);
**方法** 见 [test-design/README](test-design/README.md) 的术语表;**设计文档** 指 `docs/test-design/` 的编号。

## 1. 单测(UT)

### 1.1 状态机 —— 设计文档 01

| ID | 类 :: 方法 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| UT-SM-01 | `TransitionTableTest::edgesMatchSpecExactly` | 实现的迁移表与规格抄本逐行相等,边数 11 | 状态迁移法 | |
| UT-SM-02 | `TransitionTableTest::everyCellMatchesSpec` | 36 格 hasEdge 与规格一致 | 状态迁移法 | 36 |
| UT-SM-03 | `TransitionTableTest::legalTransitionsPass` | 11 条合法边放行、状态改变、返回 from | 状态迁移法 | 11 |
| UT-SM-04 | `TransitionTableTest::illegalTransitionsRejected` | 25 条非法边抛 IllegalTransitionException(from/to 正确),状态不变 | 状态迁移法 | 25 |
| UT-SM-05 | `TransitionTableTest::selfLoopsAreIllegal` | 6 个自环全非法 | 状态迁移法 | |
| UT-SM-06 | `TransitionTableTest::noDeadStates` | 每个状态有出边;CLOSED 只能重开、ESCALATED 只能被指派 | 状态迁移法 | |
| UT-SM-07 | `TicketStateMachineTest.ReopenGuard::exactlySevenDaysAllowed` | 重开窗口上界(7d 整)允许 | 边界值 | |
| UT-SM-08 | `…ReopenGuard::oneSecondInsideWindowAllowed` | 7d − 1s 允许 | 边界值 | |
| UT-SM-09 | `…ReopenGuard::oneSecondOutsideWindowRejected` | 7d + 1s 拒绝,消息含"7 天" | 边界值 | |
| UT-SM-10 | `…ReopenGuard::oneMillisecondOutsideWindowRejected` | 7d + 1ms 拒绝 | 边界值 | |
| UT-SM-11 | `…ReopenGuard::missingClosedAtRejected` | closedAt 为空拒绝 | 边界值(无效输入) | |
| UT-SM-12 | `…ReopenGuard::reopenImmediatelyAllowed` | 下界(刚关就重开)允许 | 边界值 | |
| UT-SM-13 | `…EntryActions::enteringPendingClearsAssignee` | 退回清 assignee | 状态迁移法(进入动作) | |
| UT-SM-14 | `…EntryActions::enteringClosedStampsClosedAt` | 关闭记 closedAt | 同上 | |
| UT-SM-15 | `…EntryActions::reopenClearsClosedAt` | 重开清 closedAt | 同上 | |
| UT-SM-16 | `…EntryActions::rejectFromWaitConfirmKeepsFields` | 用户不认可不动 closedAt/assignee | 同上 | |
| UT-SM-17 | `…EntryActions::enteringAssignedHasNoAction` | 进入 ASSIGNED 无动作 | 同上 | |
| UT-SM-18 | `…EntryActions::transitReturnsPreviousStatus` | transit 返回流转前状态 | 同上 | |
| UT-SM-19 | `TicketStateMachineTest::fullHappyPath` | 主干路径 5 条边连走 | 场景法 | |

### 1.2 工单服务编排 —— 设计文档 01 / 04

| ID | 类 :: 方法 | 覆盖什么 | 方法 |
|---|---|---|---|
| UT-TS-01 | `TicketServiceTest.Transit::legalTransitionByOwner` | 合法流转:落库 + 审计 MANUAL + STATUS_CHANGED 事件 | 场景法 |
| UT-TS-02 | `…Transit::illegalTransitionPersistsNothing` | 非法流转不落库不审计不发事件 | 场景法 |
| UT-TS-03 | `…Transit::leaderAssignsViaTransition` | 组长 transit 到 ASSIGNED 发两条事件 | 场景法 |
| UT-TS-04 | `…Transit::assignWithoutAssigneeRejected` | 缺 assigneeId → 40002 | 等价类 |
| UT-TS-05 | `…Transit::assignToOtherGroupRejected` | 跨组坐席 → 40003 | 等价类 |
| UT-TS-06 | `…Transit::agentReturnsTicketToPending` | 坐席退回,assignee 写 null | 场景法 |
| UT-TS-07 | `…Transit::agentTransitionToAssignedIsVerticalEscalation` | AGENT transit 到 ASSIGNED → 40302 | 判定表 |
| UT-TS-08 | `…Transit::othersTicketIsHorizontalEscalation` | 别人的单 → 40301,状态机不跑 | 判定表 |
| UT-TS-09 | `…Transit::notFound` | 不存在 → 40401 | 等价类 |
| UT-TS-10 | `…Grab::grabPending` | 抢单成功:ASSIGNED、审计"抢单"、两条事件 | 场景法 |
| UT-TS-11 | `…Grab::grabAlreadyAssigned` | 已分配再抢 → 40901,from/to=ASSIGNED | 状态迁移法 |
| UT-TS-12 | `…Grab::grabEscalated` | ESCALATED 不能抢 | 状态迁移法 |
| UT-TS-13 | `…Grab::grabAcrossGroup` | 跨组 → 40301 | 判定表 |
| UT-TS-14 | `…Assign::assignPending` | 指派:流转 + 两条事件 + 备注 | 场景法 |
| UT-TS-15 | `…Assign::reassign` | 改派:只换人,审计 from=to,只发 ASSIGNED | 场景法 |
| UT-TS-16 | `…Assign::assignEscalated` | ESCALATED → ASSIGNED 走状态机 | 状态迁移法 |
| UT-TS-17 | `…Assign::cannotAssignProcessing` | PROCESSING 不能改派 → 40901 | 状态迁移法 |
| UT-TS-18 | `…Assign::agentCannotAssign` | AGENT → 40302 | 判定表 |
| UT-TS-19 | `…Assign::otherGroupLeaderCannotAssign` | 别组组长 → 40301 | 判定表 |
| UT-TS-20 | `…Assign::assignToUnknownAgent` | 坐席不存在 → 40402 | 等价类 |
| UT-TS-21 | `…Others::getForbidden` | 读别人的单 → 40301 | 判定表 |
| UT-TS-22 | `…Others::updateClosed` | 已关闭不能改 → 40902 | 等价类 |
| UT-TS-23 | `…Others::updateOk` | 正常修改 | 场景法 |
| UT-TS-24 | `…Others::deleteByRole` | LEADER 40302 / ADMIN 逻辑删 | 判定表 |
| UT-TS-25 | `…Others::draftReplyDelegates` | 草稿委托 LlmService,结果原样装 VO | 场景法 |

### 1.3 SLA —— 设计文档 02

| ID | 类 :: 方法 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| UT-SLA-01 | `SlaDeadlineTest::deadlineByPriority` | P0/P1/P2 时限 15/60/240 | 等价类 | 3 |
| UT-SLA-02 | `SlaDeadlineTest::deadlineAnchoredOnCreationInstant` | 起点 = 创建时刻 | 边界值 | |
| UT-SLA-03 | `SlaDeadlineTest::crossesMidnight` | 跨天 | 边界值 | |
| UT-SLA-04 | `SlaDeadlineTest::crossesMonthBoundary` | 跨月 | 边界值 | |
| UT-SLA-05 | `SlaDeadlineTest::sameInstantDifferentZones` | 跨时区:墙钟差 8h、时长一致、同一 Instant | 边界值 | |
| UT-SLA-06 | `SlaDeadlineTest::degradedPriorityStillDrivesDeadline` | 降级优先级同样决定时限 | 场景法 | |
| UT-SLA-07 | `SlaOverdueQueryH2Test.ClosedInterval::exactlyAtDeadlineIsOverdue` | **now = D 超时(闭区间)** | 边界值(真实 SQL) | |
| UT-SLA-08 | `…ClosedInterval::oneMillisecondBeforeIsNotOverdue` | D − 1ms 未超时 | 边界值 | |
| UT-SLA-09 | `…ClosedInterval::oneSecondBeforeIsNotOverdue` | D − 1s 未超时 | 边界值 | |
| UT-SLA-10 | `…ClosedInterval::oneMillisecondAfterIsOverdue` | D + 1ms 超时 | 边界值 | |
| UT-SLA-11 | `…ClosedInterval::oneSecondAfterIsOverdue` | D + 1s 超时 | 边界值 | |
| UT-SLA-12 | `…ClosedInterval::crossesMidnight` | 23:59:59.999 vs 次日 00:00:00.000 | 边界值 | |
| UT-SLA-13 | `…Filters::respondedStatusesAreIgnored` | PROCESSING/WAIT_CONFIRM/CLOSED/ESCALATED 不扫 | 等价类 | 4 |
| UT-SLA-14 | `…Filters::unrespondedStatusesAreScanned` | PENDING/ASSIGNED 扫 | 等价类 | 2 |
| UT-SLA-15 | `…Filters::alreadyEscalatedIsIgnored` | escalated_at 非空不扫 | 等价类 | |
| UT-SLA-16 | `…Filters::deletedIsIgnored` | 逻辑删除不扫 | 等价类 | |
| UT-SLA-17 | `…Filters::orderedByDeadlineAndLimited` | 升序 + limit | 边界值 | |
| UT-SLA-18 | `…ConditionalUpdate::escalatesOnceOnly` | 条件更新 1 行后 0 行,escalated_at 不覆盖 | 场景法(真实 SQL) | |
| UT-SLA-19 | `…ConditionalUpdate::reassignedAfterEscalationIsNotEscalatedAgain` | 指派回 ASSIGNED 后不二次升级 | 场景法 | |
| UT-SLA-20 | `…ConditionalUpdate::manualProgressWinsTheRace` | 扫描后人工推进,条件更新 0 行 | 场景法 | |
| UT-SLA-21 | `SlaEscalationServiceTest::escalatesWhenConditionalUpdateHits` | 影响 1 行:审计 SCHEDULER + 两条事件 + 指标 | 判定表 | |
| UT-SLA-22 | `SlaEscalationServiceTest::skipsWhenConditionalUpdateMisses` | 影响 0 行:skipped+1,无审计无事件 | 判定表 | |
| UT-SLA-23 | `SlaEscalationServiceTest::secondCallOnSameTicketIsNoOp` | 连调两次只升级一次 | 场景法 | |
| UT-SLA-24 | `SlaEscalationServiceTest::missingTicketReturnsFalse` | 工单不存在 | 等价类 | |
| UT-SLA-25 | `SlaScannerTest::scansWithLockAndClockNow` | 持锁扫描,now 来自 Clock,释放锁 | 场景法 | |
| UT-SLA-26 | `SlaScannerTest::nothingOverdue` | 无超时单 | 场景法 | |
| UT-SLA-27 | `SlaScannerTest::skipsWhenLockHeldElsewhere` | 锁被占跳过 | 场景法 | |
| UT-SLA-28 | `SlaScannerTest::failsOpenWhenRedisDown` | Redis 挂 fail-open | 场景法 | |
| UT-SLA-29 | `SlaScannerTest::oneFailureDoesNotStopTheBatch` | 单张失败不影响批 | 场景法 | |
| UT-SLA-30 | `SlaScannerTest::scheduledScanSwallowsExceptions` | 定时方法吞异常仍释放锁 | 场景法 | |

### 1.4 LLM 路径 —— 设计文档 03

| ID | 类 :: 方法 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| UT-LLM-01 | `LlmServiceTest::normalClassify` | 判定表 R1:正常采用,degraded=false,model 有值 | 判定表 | |
| UT-LLM-02 | `LlmServiceTest::lenientEnumParsing` | R2:大小写 / 空白不算越界 | 判定表 | |
| UT-LLM-03 | `LlmServiceTest::categoryOutOfEnumFallsToOther` | R3:SPAM → OTHER,contract+1,不降级 | 判定表 | |
| UT-LLM-04 | `LlmServiceTest::priorityOutOfEnumUsesRules` | R4:P9 → 规则优先级 | 判定表 | |
| UT-LLM-05 | `LlmServiceTest::nullCategoryTreatedAsViolation` | R5:null 字段 | 判定表 | |
| UT-LLM-06 | `LlmServiceTest::timeoutFallsBackToRules` | R6:TIMEOUT 降级,latency 如实 | 判定表 | |
| UT-LLM-07 | `LlmServiceTest::everyClientFailureReasonIsRecorded` | R6~R8 三种失败原因透传 | 等价类 | 3 |
| UT-LLM-08 | `LlmServiceTest::fallbackAlwaysWithinContract` | 降级结果在枚举内 | 判定表 | |
| UT-LLM-09 | `…Circuit::fiveFailuresOpenTheCircuitAndShortCircuitTheSixthCall` | 第 5 次打开;第 6 次不调客户端,CIRCUIT_OPEN | 边界值 + 判定表 R9 | |
| UT-LLM-10 | `…Circuit::recoversAfterOpenWindow` | 59s 不放行,60s 放行恢复 | 边界值 | |
| UT-LLM-11 | `…Circuit::breakerIsSharedAcrossScenes` | 两个场景共用熔断器 | 场景法 | |
| UT-LLM-12 | `…Circuit::successBreaksTheStreak` | 成功打断连续计数 | 场景法 | |
| UT-LLM-13 | `…Circuit::contractViolationDoesNotCountAsFailure` | 越界不计入熔断 | 判定表 | |
| UT-LLM-14 | `…Draft::normalDraft` | D1 | 判定表 | |
| UT-LLM-15 | `…Draft::timeoutFallsBackToTemplate` | D2 模板含标题分类 | 判定表 | |
| UT-LLM-16 | `…Draft::badResponseCountsTowardsCircuit` | D3 | 判定表 | |
| UT-LLM-17 | `CircuitBreakerTest::fourFailuresStayClosed` | 4 次闭合 | 边界值 | |
| UT-LLM-18 | `CircuitBreakerTest::fifthFailureTrips` | 5 次打开、计数清零、openUntil | 边界值 | |
| UT-LLM-19 | `CircuitBreakerTest::successResetsConsecutiveCount` | 4+1+4 不触发 | 场景法 | |
| UT-LLM-20 | `CircuitBreakerTest::closesExactlyAfterOpenWindow` | 59.999s 打开 / 60s 闭合 | 边界值 | |
| UT-LLM-21 | `CircuitBreakerTest::reopensOnlyAfterAnotherFullRun` | 无半开 | 场景法 | |
| UT-LLM-22 | `CircuitBreakerTest::thresholdOneTripsImmediately` | 阈值 1 退化 | 边界值 | |
| UT-LLM-23 | `KeywordRuleClassifierTest::classifiesByKeywordTable` | 9 组关键词 → 类别 / 优先级 | 等价类 | 9 |
| UT-LLM-24 | `KeywordRuleClassifierTest::nullInputsFallToOther` | null / 空 | 等价类 | |
| UT-LLM-25 | `KeywordRuleClassifierTest::deterministic` | 确定性 | 等价类 | |
| UT-LLM-26 | `KeywordRuleClassifierTest::priorityOfMatrix` | 优先级矩阵 | 判定表 | |
| UT-LLM-27 | `WireMockLlmClientTest::classifyHappyPath` | 请求组装 + 原样返回(含越界) | 等价类 | |
| UT-LLM-28 | `WireMockLlmClientTest::classifyMissingFieldsBecomeNull` | 缺字段 → null | 等价类 | |
| UT-LLM-29 | `WireMockLlmClientTest::nonJsonBodyIsBadResponse` | 非 JSON → BAD_RESPONSE | 等价类 | |
| UT-LLM-30 | `WireMockLlmClientTest::serverErrorIsUpstream` / `tooManyRequestsIsUpstream` | 500 / 429 → UPSTREAM_ERROR | 等价类 | |
| UT-LLM-31 | `WireMockLlmClientTest::draftHappyPath` / `draftMissingFieldIsBadResponse` / `draftNullIsBadResponse` | 草稿解析 | 等价类 | |
| UT-LLM-32 | `LlmHttpSupportTest::*`(7 条) | 异常 → DegradeReason 翻译(含 Spring TimeoutException 包裹) | 等价类 | |

### 1.5 MQ —— 设计文档 06

| ID | 类 :: 方法 | 覆盖什么 | 方法 |
|---|---|---|---|
| UT-MQ-01 | `IdempotentConsumerSupportTest::sameMessageDeliveredTwiceRunsBusinessOnce` | **同一消息投递两次业务只跑一次** | 场景法 C2 |
| UT-MQ-02 | `…::sameMessageDifferentConsumersEachRunOnce` | 不同消费者各一次 | 场景法 C3 |
| UT-MQ-03 | `…::firstConsumptionWritesFullDedupRow` | 去重行字段 | 场景法 C1 |
| UT-MQ-04 | `…::businessFailurePropagatesAndDoesNotCount` | 业务失败传播、不计 consumed | 场景法 C5 |
| UT-MQ-05 | `…::duplicateIsSilentlySkipped` | 重复不抛 | 场景法 C2 |
| UT-MQ-06 | `…::traceIdPropagatedToMdcAndCleared` / `missingTraceIdFallsBackToMessageId` | MDC | 场景法 C6 |
| UT-MQ-07 | `MqMessageDedupH2Test::duplicateInsertThrowsDuplicateKeyException` | 真实唯一键抛 DuplicateKeyException | 场景法(真实 SQL) |
| UT-MQ-08 | `MqMessageDedupH2Test::differentConsumersDoNotCollide` | 复合唯一键 | 同上 |
| UT-MQ-09 | `TicketEventPublisherTest::routesByEventTypeAndMapsFields` / `routingKeys` | 路由键、字段映射 | 场景法 P1/P2 |
| UT-MQ-10 | `TicketEventPublisherTest::messageIdIsUniquePerSend` | id 唯一 | P3 |
| UT-MQ-11 | `TicketEventPublisherTest::brokerDownIsCountedNotThrown` | Broker 挂只打点 | P4 |
| UT-MQ-12 | `TicketEventPublisherTest::consumersUseTheirOwnNames` | 三个消费者名字 | C8 |

### 1.6 权限 / 附件 / Web 层 / 辅助 —— 设计文档 04 / 05

| ID | 类 :: 方法 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| UT-AC-01 | `AccessCheckerTest::readTable` / `writeTable` | 读写判定表 8 行 | 判定表 | 8+8 |
| UT-AC-02 | `AccessCheckerTest::grabTable` | 抢单判定表 5 行 | 判定表 | 5 |
| UT-AC-03 | `AccessCheckerTest::assignTable` | 改派判定表 5 行(40302 先于 40301) | 判定表 | 5 |
| UT-AC-04 | `AccessCheckerTest.RequireRole::*`(3 条) | 纯角色检查 | 等价类 | |
| UT-AT-01 | `AttachmentServiceTest::validPngStoredUnderUuid` / `validTxtWithCharsetParameter` | 合法上传、UUID、库记录 | 等价类 | |
| UT-AT-02 | `AttachmentServiceTest::exactlyMaxSizeAllowed` / `oneByteOverMaxRejected` / `emptyFileRejected` | 5MB 闭区间、0 字节 | 边界值 | |
| UT-AT-03 | `…Bypass::extensionNotInWhitelist` | L1 无效类 7 个 | 等价类 | 7 |
| UT-AT-04 | `…Bypass::declaredMimeMismatch` / `missingContentType` | L2 无效类 | 等价类 | |
| UT-AT-05 | `…Bypass::magicMismatchPhpAsJpg` / `pngContentNamedJpg` / `binaryAsTxt` | L3 无效类 | 等价类 | |
| UT-AT-06 | `…Bypass::pathTraversalNeutralised` / `windowsPathTraversalNeutralised` | 路径穿越 | 等价类 | |
| UT-AT-07 | `AttachmentServiceTest::sizeCheckedBeforeExtension` / `accessCheckedFirst` | 校验顺序 | 场景法 | |
| UT-AT-08 | `AttachmentServiceTest::extensionOf` / `normalizeMime` | 纯函数 | 等价类 | 6+4 |
| UT-AT-09 | `FileTypeSnifferTest::*`(11 条) | 魔数 / 文本判定、截断边界 | 等价类 + 边界值 | |
| UT-WEB-01 | `TicketControllerWebTest.Auth::*`(4 条) | 401 拦截器、actuator 不拦 | 等价类 | |
| UT-WEB-02 | `TicketControllerWebTest.Validation::*`(9 条) | Bean Validation → 400/40001 | 等价类 + 边界值 | |
| UT-WEB-03 | `TicketControllerWebTest.ExceptionMapping::*`(5 条) | 409/403/404/500 映射、不泄漏异常 | 等价类 | |
| UT-WEB-04 | `TicketControllerWebTest.Envelope::*`(3 条) | 统一信封、traceId 透传 / 生成、non_null | 场景法 | |
| UT-AUX-01 | `PersistenceHelpersTest::*`(4 条) | 审计 traceId、LLM 记录绑定、坐席停用视为不存在 | 等价类 | |

## 2. 接口自动化(API)

### 2.1 基础与工单 CRUD —— 设计文档 04 / 06

| ID | 文件 :: 用例 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| API-BASE-01 | `test_health_auth.py::TestHealth::test_health_up` | health UP,db/redis/rabbit | 冒烟 | |
| API-BASE-02 | `…::test_custom_metrics_exposed` | 启动即注册的指标存在 | 冒烟 | |
| API-BASE-03 | `…::test_actuator_needs_no_auth` | actuator 不需鉴权 | 等价类 | |
| API-AUTH-01 | `…TestAuth::test_missing_header` | 无头 401 | 等价类 | |
| API-AUTH-02 | `…::test_invalid_header_values` | 非法头值 401 | 等价类 | 8 |
| API-AUTH-03 | `…::test_unknown_user` | 不存在 401 | 等价类 | |
| API-AUTH-04 | `…::test_seed_users` | 6 个种子坐席角色 / 组 | 等价类 | 6 |
| API-AUTH-05 | `…::test_trace_id_passthrough` | X-Trace-Id 透传 | 场景法 | |
| API-CR-01 | `test_ticket_create.py::TestCreateContract::test_create_returns_full_contract` | 创建契约:字段、单号格式、PENDING、无 assignee | 等价类 | |
| API-CR-02 | `…::test_group_default_and_explicit` | groupId 缺省 1 | 等价类 | |
| API-CR-03 | `…::test_sla_deadline_equals_created_plus_limit` | 截止 = 创建 + 时限 | 边界值 | 3 |
| API-CR-04 | `…::test_initial_audit_log` | 首条审计 LLM,llm_call_log 已绑定 | 场景法 | |
| API-CR-05 | `…::test_updated_at_changes_after_transition` | updatedAt 随更新变化 | 场景法 | |
| API-CR-06 | `…TestCreateValidation::test_invalid_bodies` | 10 个无效等价类 → 40001 指出字段 | 等价类 + 边界值 | 10 |
| API-CR-07 | `…::test_title_length_boundaries` | 标题 1 / 200 字 | 边界值 | 2 |
| API-CR-08 | `…::test_content_upper_boundary` | 内容 5000 字 | 边界值 | |
| API-CR-09 | `…::test_malformed_bodies` | 5 种坏请求体 | 等价类 | 5 |
| API-CR-10 | `…::test_unknown_fields_ignored` | 未知字段忽略,不能注入 status/id | 等价类 | |
| API-CRUD-01 | `test_ticket_crud.py::TestCrud::test_get` | 详情 / 404 | 等价类 | |
| API-CRUD-02 | `…::test_update` | 修改落库、不产生审计 | 场景法 | |
| API-CRUD-03 | `…::test_update_validation` | 修改参数校验 | 等价类 | 3 |
| API-CRUD-04 | `…::test_delete_is_logical` | 逻辑删除:404、列表不含、deleted=1 | 场景法 | |
| API-CRUD-05 | `…::test_delete_missing_and_twice` | 删不存在 / 重复删 | 等价类 | |
| API-AUD-01 | `…TestAudit::test_audit_matches_every_transition` | 每次流转恰好一条,operator/from/to/traceId 一致,接口 == 库表 | 场景法 | |
| API-AUD-02 | `…::test_audit_permission` | 审计读权限 | 判定表 | |

### 2.2 状态机 —— 设计文档 01

| ID | 文件 :: 用例 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| API-SM-01 | `test_state_machine.py::TestIllegalTransitions::test_illegal_cell` | **25 格非法流转** 409/40901、状态不变、审计不增 | 状态迁移法 | 25 |
| API-SM-02 | `…TestLegalPaths::test_main_path_with_audit` | 主干 5 条边 + 审计逐条 | 状态迁移法 + 场景法 | |
| API-SM-03 | `…::test_return_to_pending_clears_assignee` | 退回清 assignee,可再抢 | 状态迁移法 | |
| API-SM-04 | `…::test_customer_rejects` | 用户不认可 | 状态迁移法 | |
| API-SM-05 | `…::test_manual_escalate` | 三个起点人工升级 | 状态迁移法 | 3 |
| API-SM-06 | `…::test_escalated_back_to_assigned` | ESCALATED 只能指派不能抢 | 状态迁移法 | |
| API-SM-07 | `…TestReopenWindow::test_reopen_inside_window` | 6.9 天可重开 | 边界值 | |
| API-SM-08 | `…::test_reopen_outside_window` | 7 天零 1 分钟拒绝 | 边界值 | |
| API-SM-09 | `…::test_closed_ticket_is_immutable` | 已关闭不能改 40902 | 等价类 | |

### 2.3 抢单 / 指派 / 列表 —— 设计文档 04

| ID | 文件 :: 用例 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| API-GR-01 | `test_grab_assign.py::TestGrab::test_grab_pending` | 抢单成功 + 审计"抢单" | 场景法 | |
| API-GR-02 | `…::test_grab_twice` | 再抢 409,assignee 不变 | 状态迁移法 | |
| API-GR-03 | `…::test_grab_across_group` | 跨组 40301 | 判定表 | 2 |
| API-GR-04 | `…::test_leader_and_admin_can_grab` | 组长 / ADMIN 可抢 | 判定表 | |
| API-GR-05 | `…::test_grab_missing` | 404 | 等价类 | |
| API-AS-01 | `…TestAssign::test_leader_assigns_pending` | 指派 + 备注 | 场景法 | |
| API-AS-02 | `…::test_leader_reassigns` | 改派:审计 from=to、新旧坐席权限交接 | 场景法 | |
| API-AS-03 | `…::test_assign_to_other_group_agent` | 40003 | 等价类 | |
| API-AS-04 | `…::test_assign_to_unknown_agent` | 40402 | 等价类 | |
| API-AS-05 | `…::test_assign_invalid_body` | assigneeId 5 种无效 | 等价类 | 5 |
| API-AS-06 | `…::test_transition_to_assigned_requires_assignee` | 40002 | 等价类 | |
| API-AS-07 | `…::test_admin_assigns_any_group` | ADMIN 跨组 | 判定表 | |
| API-AS-08 | `…::test_cannot_reassign_processing` | PROCESSING 不能改派 | 状态迁移法 | |
| API-LS-01 | `…TestList::test_agent_sees_own_only` | AGENT 收窄 | 判定表 | |
| API-LS-02 | `…::test_leader_sees_group` | LEADER 收窄 | 判定表 | |
| API-LS-03 | `…::test_admin_sees_all_with_filter` | ADMIN + status 过滤 | 判定表 | |
| API-LS-04 | `…::test_pagination_shape` | 分页字段 | 等价类 | |
| API-LS-05 | `…::test_invalid_paging` | page/size/status 越界 | 边界值 | 6 |

### 2.4 SLA —— 设计文档 02

| ID | 文件 :: 用例 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| API-SLA-01 | `test_sla.py::TestEscalation::test_overdue_pending_is_escalated` | 超时 PENDING 升级:状态、escalatedAt、审计 SCHEDULER、指标 | 场景法 S1 | |
| API-SLA-02 | `…::test_overdue_assigned_is_escalated` | 超时 ASSIGNED 升级,assignee 保留 | 场景法 | |
| API-SLA-03 | `…::test_responded_ticket_not_escalated` | 已响应三种状态不升级 | 等价类 | 3 |
| API-SLA-04 | `…::test_deadline_in_near_future` | now+3s 不命中 → 3.5s 后命中 | 边界值 | |
| API-SLA-05 | `…::test_scan_permission` | 扫描只有 ADMIN | 判定表 | |
| API-SLA-06 | `…TestNoDoubleEscalation::test_second_scan_is_noop` | 连扫两轮只升级一次 | 场景法 S3 | |
| API-SLA-07 | `…::test_reassigned_after_escalation_not_escalated_again` | 指派回后不二次升级 | 场景法 S4 | |
| API-SLA-08 | `…::test_batch_escalation` | 三张一轮全升级 | 场景法 S6 | |
| API-SLA-09 | `…TestEscalationEvents::test_escalation_publishes_two_events` | 升级发两类事件被消费 | 场景法 P7 | |

### 2.5 LLM 路径 —— 设计文档 03

| ID | 文件 :: 用例 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| API-LLM-01 | `test_llm_classify.py::TestNormalClassification::test_keyword_routes` | R1 四类关键词;**degraded=0、model 非空、挡板收到带标题的请求** | 判定表 | 4 |
| API-LLM-02 | `…::test_ambiguous_keywords` | 多类命中:在枚举内且未降级(KI-006) | 判定表 | |
| API-LLM-03 | `…::test_latency_recorded` | 耗时 < 2.5s,latency_ms 如实 | 边界值 | |
| API-LLM-04 | `…TestDegradation::test_timeout_falls_back_to_rules` | R6:[SLOW] ≥ 3000ms,TIMEOUT,规则,指标,挡板收到 1 个请求,审计备注 | 判定表 | |
| API-LLM-05 | `…::test_upstream_error_falls_back` | R7:[ERROR] | 判定表 | |
| API-LLM-06 | `…::test_bad_json_falls_back` | R8:[BAD_JSON] | 判定表 | |
| API-LLM-07 | `…::test_degraded_result_stays_in_contract` | 降级结果在枚举内([ERROR] 含 error → TECH) | 判定表 | |
| API-LLM-08 | `…TestContractViolation::test_out_of_enum_category` | R3:[BAD_CATEGORY] SPAM → OTHER,不降级,contract 指标 | 判定表 | |
| API-LLM-09 | `…::test_out_of_enum_priority_via_temp_stub` | R4:临时桩 P9 → 规则优先级 | 判定表 | |
| API-LLM-10 | `…TestDraftReply::test_normal_draft` | D1 | 判定表 | |
| API-LLM-11 | `…::test_timeout_draft_uses_template` | D2 | 判定表 | |
| API-LLM-12 | `…::test_upstream_error_draft` | D4 | 判定表 | |
| API-LLM-13 | `…::test_draft_permission` | 草稿写权限 | 判定表 | |
| API-CB-01 | `test_llm_circuit.py::TestCircuitBreaker::test_five_failures_open_the_circuit` | 前 4 次闭合,第 5 次打开,指标 | 边界值 | |
| API-CB-02 | `…::test_open_circuit_short_circuits_everything` | R9/D5:CIRCUIT_OPEN、latency=0、**挡板收到 0 个请求**、草稿也短路 | 判定表 | |
| API-CB-03 | `…::test_recovers_after_open_window` | ≤65s 恢复,重新由模型分类 | 边界值 | |
| API-CB-04 | `…::test_no_half_open_state` | 恢复后 4 次失败仍闭合 | 场景法 | |

### 2.6 MQ —— 设计文档 06

| ID | 文件 :: 用例 | 覆盖什么 | 方法 |
|---|---|---|---|
| API-MQ-01 | `test_mq_idempotency.py::TestDelivery::test_grab_publishes_two_events` | P5 两条事件各自消费,id 唯一,指标 | 场景法 |
| API-MQ-02 | `…::test_trace_id_propagates_to_consumer` | P8 traceId 跨线程 | 场景法 |
| API-MQ-03 | `…::test_illegal_transition_publishes_nothing` | P6 | 场景法 |
| API-MQ-04 | `…TestIdempotency::test_redelivery_is_deduplicated` | **C2 同一 messageId 重投:去重表不增、consumed 不增、duplicate+1** | 场景法 |
| API-MQ-05 | `…::test_new_message_id_is_processed` | C4 | 场景法 |
| API-MQ-06 | `…::test_same_id_different_consumers` | C3 | 场景法 |
| API-MQ-07 | `…::test_queues_drain` | C7 | 场景法 |

### 2.7 附件 —— 设计文档 05

| ID | 文件 :: 用例 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| API-AT-01 | `test_attachments.py::TestUpload::test_valid_types` | 四种类型 + 大写扩展名:201、UUID、库表、落盘内容一致 | 等价类 | 5 |
| API-AT-02 | `…::test_size_boundary` | 5MB / 5MB+1 | 边界值 | |
| API-AT-03 | `…::test_empty_file` | 41501 | 边界值 | |
| API-AT-04 | `…::test_missing_part` | 40001 | 等价类 | |
| API-AT-05 | `…::test_list` | 列表顺序 | 场景法 | |
| API-AT-06 | `…::test_permissions` | 写 / 读权限 | 判定表 | |
| API-AT-07 | `…::test_missing_ticket` | 40401 | 等价类 | |

## 3. 安全(SEC)—— 设计文档 04 / 05 / 07

| ID | 文件 :: 用例 | 覆盖什么 | 方法 | 参数化 |
|---|---|---|---|---|
| SEC-H-01 | `test_horizontal_privilege.py::test_every_endpoint_rejects_non_owner` | **7 接口 × 3 入侵者 = 21 条水平越权**,全 40301,无副作用 | 判定表 | 21 |
| SEC-H-02 | `…::test_owner_leader_admin_allowed` | 对照组放行 | 判定表 | |
| SEC-H-03 | `…::test_pending_ticket_visibility` | PENDING 单可抢不可看,抢后交接 | 判定表 | |
| SEC-H-04 | `…::test_cross_group_leader` | 跨组组长读写改派全 40301 | 判定表 | |
| SEC-H-05 | `…::test_id_enumeration_sweep` | IDOR 扫描,不泄露 | 场景法 | |
| SEC-H-06 | `…::test_list_does_not_leak` | 列表不泄露 | 判定表 | |
| SEC-V-01 | `test_vertical_privilege.py::TestAssignIsLeaderOnly::test_agent_cannot_assign_even_own_ticket` | AGENT 改派 40302 | 判定表 | |
| SEC-V-02 | `…::test_agent_cannot_assign_via_transitions` | 绕开 assign 接口仍 40302(Service 层校验) | 判定表 | |
| SEC-V-03 | `…::test_check_order_on_pending` | 检查顺序 checkWrite → checkAssign | 判定表 | |
| SEC-V-04 | `…::test_leader_scope` | 跨组组长 40301 vs 本组放行 | 判定表 | |
| SEC-V-05 | `…TestAdminOnly::test_delete_requires_admin` | 三角色删除 40302 | 判定表 | 3 |
| SEC-V-06 | `…::test_sla_scan_requires_admin` | 扫描 40302 | 判定表 | 2 |
| SEC-V-07 | `…::test_admin_allowed` | ADMIN 对照 | 判定表 | |
| SEC-V-08 | `…TestRoleForgery::test_role_cannot_be_injected` | 角色不能经 query/头/body 伪造 | 等价类 | |
| SEC-V-09 | `…::test_user_id_header_tricks` | 多值 / 控制字符头 401 | 等价类 | |
| SEC-SQL-01 | `test_sql_injection.py::test_string_fields_are_parameterised` | 10 个字符串载荷原样存取,表不变 | 等价类 | 10 |
| SEC-SQL-02 | `…::test_status_param_is_enum_bound` | 枚举参数 400 | 等价类 | 4 |
| SEC-SQL-03 | `…::test_path_id_is_typed` | 路径 id 400/404 不 500 | 等价类 | 6 |
| SEC-SQL-04 | `…::test_path_id_tolerated_suffixes` | 分号 / 空白尾巴被框架剥掉(观察项 KI-005) | 等价类 | 3 |
| SEC-SQL-05 | `…::test_paging_params_are_typed` | 分页参数 400 | 等价类 | 3 |
| SEC-SQL-06 | `…::test_assignee_id_is_typed` | assigneeId 400 | 等价类 | |
| SEC-SQL-07 | `…::test_user_header_injection` | 头注入 401 | 等价类 | |
| SEC-SQL-08 | `…::test_no_time_based_injection` | SLEEP 不生效 | 等价类 | |
| SEC-AT-01 | `test_attachment_bypass.py::TestExtensionLayer::test_extension_not_whitelisted` | L1 18 个无效扩展名 | 等价类 | 18 |
| SEC-AT-02 | `…::test_null_byte_truncation` | 空字节截断 | 等价类 | |
| SEC-AT-03 | `…::test_double_extension_last_dot_wins` | 双扩展名 | 等价类 | |
| SEC-AT-04 | `…TestMimeLayer::test_declared_mime_mismatch` | L2 6 种声明不符(含 KI-004) | 等价类 | 6 |
| SEC-AT-05 | `…::test_declared_mime_with_parameter_allowed` | 带参数 MIME 放行 | 等价类 | |
| SEC-AT-06 | `…::test_mime_cannot_rescue_extension` | L1 先于 L2 | 场景法 | |
| SEC-AT-07 | `…TestContentLayer::test_magic_mismatch` | L3 9 种内容 / 扩展名不符 | 等价类 | 9 |
| SEC-AT-08 | `…::test_php_as_txt_is_stored_inert` | PHP 作 txt 合法且不可执行 | 等价类 | |
| SEC-AT-09 | `…::test_polyglot_png_php` | polyglot → **xfail KI-002** | 等价类 | |
| SEC-AT-10 | `…TestPathAndSize::test_path_traversal_neutralised` | 7 种路径穿越,UUID 落盘,目录外无文件 | 等价类 | 7 |
| SEC-AT-11 | `…::test_overlong_filename` | 300 字符名截断 255 | 边界值 | |
| SEC-AT-12 | `…::test_oversize` | 5MB+1 / 8MB+1 | 边界值 | |
| SEC-AT-13 | `…::test_duplicate_parts` | 两个 file 字段 | 等价类 | |
| SEC-PII-01 | `test_pii_masking.py::test_current_behaviour_phone_is_plain` | 事实:四处明文 | 探测 | |
| SEC-PII-02 | `…::test_pii_is_sent_to_llm` | 事实:原文发给 LLM | 探测 | |
| SEC-PII-03 | `…::test_detail_masks_phone` | 期望详情脱敏 → **xfail KI-001** | 探测 | |
| SEC-PII-04 | `…::test_list_masks_phone` | 期望列表脱敏 → **xfail KI-001** | 探测 | |

## 4. 性能模板(PERF)—— 只出脚本,不出结论

| ID | 脚本 | 链路 | 可配参数 |
|---|---|---|---|
| PERF-01 | `tests/perf/grab_race.jmx` | setUp 建 1 张 PENDING 单 → N 线程集合点同时 grab → tearDown 取终态与审计 | threads / rampup / groupId / agentsCsv / resultsFile |
| PERF-02 | `tests/perf/ticket_create.jmx` | N 线程持续创建工单 duration 秒,标题池决定挡板分支 | threads / rampup / duration / thinkMs / titlesCsv / resultsFile |
| PERF-03 | `tests/perf/run_ladder.sh` | 同一脚本按并发梯度连跑 | LADDER / DURATION |

## 5. 修复阶段新增(2026-09-21)—— 设计文档 08

### 5.1 单测

| ID | 类 :: 方法 | 覆盖什么 | 方法 |
|---|---|---|---|
| UT-GL-01..05 | `GrabLockTest` | SET NX 成功 / 被占 / Redis 异常 fail-open;release 只删自己的锁、空 token 不碰 Redis、异常吞掉 | 判定表 |
| UT-TS-20 | `TicketServiceTest.Grab::grabPending` | 条件更新带 version、审计 from=PENDING、version 回填 +1、锁释放 | 场景法 |
| UT-TS-21 | `…Grab::conditionalUpdateMissIsConflict` | 条件更新 0 行 → 40901、不审计不发事件、`grab_conflict_total` +1、锁仍释放 | 场景法 |
| UT-TS-22 | `…Grab::lockContendedRejectsBeforeDb` | 锁被占 → 40904,不 SELECT 不开事务 | 场景法 |
| UT-TS-23 | `…Grab::lockUnavailableFallsOpen` | Redis 不可用照常进库 | 场景法 |
| UT-TS-24 | `…Transit::versionConflictPersistsNoAudit` | 乐观锁 0 行 → 40903,不审计,`ticket_version_conflict_total` +1 | 场景法 |
| UT-TS-25 | `…Assign::reassignLosesRaceToGrab` | 改派读到过期快照 → 40903 | 场景法 |
| UT-H2-10 | `SlaOverdueQueryH2Test.ConditionalUpdate::staleFromStatusDoesNotEscalate` | KI-009 的 SQL 级复现:快照 PENDING、行已 ASSIGNED → 0 行;下一轮以真值升级 | 场景法(真 SQL) |
| UT-H2-11..13 | `…GrabConditionalUpdate::*` | grabIfPending 首次 1 行余下 0 行;version 不匹配 0 行;乐观锁插件改写 updateById | 真 SQL |
| UT-NO-01..04 | `TicketNoGeneratorTest` | 形状 26 字符;100 万个同毫秒无重复;32 bit 对照必碰撞;日期段随传入时刻 | 统计 / 等价类 |
| UT-LM-01..02 | `LlmMetricsTest` | 标签组合启动预注册为 0;打点落在同一 Counter | 等价类 |
| UT-SLA-xx | `SlaEscalationServiceTest`(改) | 条件更新带 from / version | 判定表 |

### 5.2 接口自动化

| ID | 文件 :: 用例 | 覆盖什么 | 方法 |
|---|---|---|---|
| API-CC-01..02 | `test_concurrency.py::TestGrabRace::test_only_one_wins[t2,t10]` | 同时抢单恰 1 个 200;审计恰 1 行且连续;三层计数恒等式 | 场景法 |
| API-CC-03 | `…::test_five_rounds_of_two` | 压测最小复现档位 5 轮 | 场景法 |
| API-CC-04 | `…TestAssignVsGrab::test_leader_assign_races_agent_grab` | 指派 vs 抢单四种合法结局的不变量,5 轮 | 判定表 |
| API-CC-05..08 | `…TestTransitionRace::*` | ASSIGNED 互斥对恰 1 个 200;WAIT_CONFIRM 非互斥对连续;同目标两次;改标题 vs 流转 version 增量 | 判定表 |
| API-AC-01..04 | `test_audit_chain.py` | 完整生命周期 / 分支路径 / 拒绝不留行 / 全库扫描 0 断裂(用例自造 3 张工单保证扫描非空,不 skip) | 反向断言 |
| API-CP-01..03 | `test_capacity.py` | MQ 生产 > 消费不丢且清空;SLA 250 张高峰每张恰 1 次;池满消费者不饿死 | 场景法 |
| API-LD-01..03 | `test_llm_draft_faults.py` | 草稿 TIMEOUT / UPSTREAM_ERROR 降级;草稿 + 分类共用熔断器 | 判定表 |
| API-FI-01..02 | `test_fault_injection.py` | RabbitMQ 停机可观测、不补投、恢复 SLO;Redis 停机 fail-open、恢复 SLO | 场景法 |
| API-CB-05 | `test_llm_circuit.py::test_still_degraded_while_dependency_is_healthy` | 挡板恢复但熔断未到期仍降级 | 场景法 |
| API-OB-01..03 | `test_health_auth.py` | 三层防线 + Tomcat 指标;LLM 标签预注册;文件日志 traceId | 等价类 |
| API-TC-xx | `test_ticket_create.py::test_ticket_no_unique_under_concurrency` | 100 张并发单号唯一、64 bit 形状 | 统计 |

### 5.3 性能模板新增

| 脚本 | 用途 |
|---|---|
| `ticket_read.jmx` | 读链路(详情 / 列表 / 修改)拐点;发现 KI-017 |
| `tools/regress_grab.sh`、`tools/ladder_full.sh` | 竞态回归与全梯度,与修复前同档位 |
| `tools/to_platform.py` | 一轮产物 → 平台导入 |

## 6. 规格条目 → 用例 追溯

| CLAUDE.md 条目 | 主要用例 |
|---|---|
| §5.1 状态机 6 行合法流转、其余非法 | UT-SM-01~06、API-SM-01~06 |
| §5.1 重开限 7 天 | UT-SM-07~12、API-SM-07~08 |
| §5.3 时限 15/60/240、起点创建时刻 | UT-SLA-01~06、API-CR-03 |
| §5.3 闭区间"恰好等于即超时" | **UT-SLA-07**(真实 SQL)、API-SLA-04(两侧夹逼) |
| §5.3 同一工单不能升级两次 | UT-SLA-18~23、API-SLA-06~08 |
| §5.4 三类事件走 MQ | UT-MQ-09、API-MQ-01、API-SLA-09 |
| §5.4 消费端幂等(去重表) | **UT-MQ-01、UT-MQ-07、API-MQ-04** |
| §5.5 分类越界 → OTHER + 打点 | UT-LLM-03、API-LLM-08 |
| §5.5 超时 3 秒 → 规则 | UT-LLM-06、API-LLM-04 |
| §5.5 连续失败 5 次 → 熔断 60 秒 | UT-LLM-09~10、UT-LLM-17~21、API-CB-01~04 |
| §5.5 每次调用落盘 | API-LLM-01/04/08/10(llm_call_log 各字段) |
| §5.5 指标 llm_fallback_total / llm_circuit_open_total | API-LLM-04~06、API-CB-01~02 |
| §5.6 AGENT 只读写自己的 / LEADER 本组 / ADMIN 全权 | UT-AC-01~03、SEC-H-01~06、SEC-V-01~07 |
| §5.6 越权校验在 Service 层 | SEC-V-02、UT-TS-07 |
| §5.7 白名单 / 5MB / UUID / 扩展名 + MIME | UT-AT-*、API-AT-*、SEC-AT-* |
| §5.8 审计:谁、何时、从哪到哪、来源 | API-AUD-01、API-SLA-01、API-CR-04 |
| §6 统一异常、错误码、Result 信封、traceId | UT-WEB-01~04、API-AUTH-05、`Expect.error` 每次都断前三位 |
