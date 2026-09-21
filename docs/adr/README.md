# 决策记录索引

每条 ADR 固定五节:背景 / 选项 / 决定 / 后果 / 常见质疑与回应。"常见质疑与回应"写成可以直接说出口的话——它回答的是"为什么不用 X"。
决策改了不改旧 ADR 的正文,在旧 ADR 里加一段"更新"指向新 ADR(ADR-002 / 004 / 006 都有)。

## 被测服务(v0.1-service)

| 编号 | 标题 | 对应代码 |
|---|---|---|
| [ADR-001](ADR-001-状态机数据驱动.md) | 状态机用"枚举 + 流转表"数据驱动,不用 if-else | `statemachine/TransitionTable`、`TicketStateMachine` |
| [ADR-002](ADR-002-状态变更与审计日志的事务边界.md) | 状态变更、审计、MQ 发送、LLM 调用各在事务哪一侧 | `TicketService`、`AuditLogService`、`TicketEventPublisher`、`LlmCallLogService` |
| [ADR-003](ADR-003-MQ消费幂等用MySQL去重表.md) | MQ 消费幂等用 MySQL 去重表,不用 Redis setnx | `mq/IdempotentConsumerSupport`、`mq_message_dedup` 表 |
| [ADR-004](ADR-004-LLM降级与熔断阈值.md) | LLM 超时 / 熔断 / 契约校验阈值与归类 | `llm/LlmService`、`CircuitBreaker`、`LlmMetrics` |
| [ADR-005](ADR-005-索引设计.md) | 索引怎么建——哪些查询走哪个索引、是否回表 | `ops/mysql/init/01-schema.sql` |
| [ADR-006](ADR-006-SLA闭区间与防重复触发.md) | SLA 闭区间、条件更新防重复、Clock 注入 | `sla/SlaScanner`、`SlaEscalationService`、`TicketMapper` |
| [ADR-007](ADR-007-越权校验放Service层.md) | 认证简化为 X-User-Id,授权全放 Service 层 | `auth/AuthInterceptor`、`AccessChecker` |
| [ADR-008](ADR-008-附件三层校验.md) | 附件扩展名 / 声明 MIME / 魔数三层校验 | `attachment/AttachmentService`、`FileTypeSniffer` |
| [ADR-009](ADR-009-LlmClient双实现与挡板契约.md) | LlmClient 双实现按配置装配,挡板用简化契约 | `llm/LlmClientConfig`、`WireMockLlmClient`、`ops/wiremock/mappings` |
| [ADR-010](ADR-010-依赖取舍.md) | 为什么没有 Lombok / Spring Security / Resilience4j / MapStruct | `service/pom.xml` |

## 测试阶段(v0.2-tests)

| 编号 | 标题 | 对应代码 |
|---|---|---|
| [ADR-011](ADR-011-增量覆盖率门禁阈值.md) | 增量覆盖率门禁 80%、全量兜底 70/60,为什么不是 100%;分母排除项的理由 | `service/pom.xml` jacoco、`.github/workflows/ci.yml` diff-cover |
| [ADR-012](ADR-012-接口自动化自研封装.md) | pytest + requests 自研四层封装,不用 HttpRunner;断言 DSL、造数清理、三层 fixture、熔断隔离 | `tests/api/framework/`、`tests/conftest.py` |
| [ADR-013](ADR-013-单测挡板选型.md) | 单测按被测对象分三种替身:Mockito / MockRestServiceServer / H2 切片;不用 Testcontainers | `service/src/test/java/com/ticketqa/support/`、`sla/SlaOverdueQueryH2Test` |
| [ADR-014](ADR-014-已知问题的挂法.md) | 测出的缺陷用 xfail(strict) 挂在套件里,不修不删不 skip | `tests/security/test_pii_masking.py`、`docs/findings/known-issues.md` |
| [ADR-015](ADR-015-CI流水线编排.md) | CI 复用 docker-compose 起中间件、java -jar 起服务;Allure 归档为 artifact | `.github/workflows/ci.yml` |

## 修复与平台阶段(v0.4-fix,2026-09-21;压测与故障注入 v0.3-perf 的结论驱动)

| 编号 | 标题 | 对应代码 |
|---|---|---|
| [ADR-016](ADR-016-抢单竞态修复-条件更新为根治-分布式锁只是削峰.md) | 抢单竞态三层修复:条件 UPDATE 根治、version 兜底、Redis 锁只是削峰(fail-open);为什么锁不能是正确性保证 | `TicketService.grab`、`TicketMapper.grabIfPending`、`GrabLock`、`MybatisPlusConfig` |
| [ADR-017](ADR-017-审计from_status取写时刻的前值.md) | 审计 from_status 只在 UPDATE 命中 1 行后写——快照读 vs 当前读;SLA 升级带 status/version;反向断言 | `TicketService.updateOrConflict`、`SlaEscalationService`、`tests/api/framework/audit.py` |
| [ADR-018](ADR-018-MQ丢失可观测替代补投-规格差异登记.md) | 规格要求"不丢、补投",实现放弃,以可观测替代——规格差异登记表与钉住它的用例 | `TicketEventPublisher`、`tests/api/test_fault_injection.py` |
| [ADR-019](ADR-019-ticket_no位宽64bit与生日碰撞.md) | 单号随机段 32 → 64 bit,生日碰撞的期望计算,100 万次单测对照 | `TicketNoGenerator`、`TicketNoGeneratorTest` |
| [ADR-020](ADR-020-故障恢复时长SLO与熔断定值.md) | Redis / RabbitMQ 恢复 SLO 45 s、熔断定值 60 s 显式接受;阈值从重连退避机制推导 | `tests/api/test_fault_injection.py`、`test_llm_circuit.py` |
| [ADR-021](ADR-021-压测结果可复现-连接池预热与并发断言写法.md) | 并发用例先把连接池撑满,只断言正确性不断言分布;为什么不固定池大小 | `tests/api/framework/pool.py`、`tests/tools/warm_pool.py`、CI 预热步骤 |
| [ADR-022](ADR-022-质量数据平台的范围与数据模型.md) | 平台只做三件事;性能基线连同环境状态存 JSON 列,环境不同结论降级为不可信;阈值 10% / 20% 的来源 | `platform/`、`PerfComparator` |
| [ADR-023](ADR-023-容量用例的前提由环境构造-小池而不是skip.md) | 容量用例的前提"池被打满"由环境构造:CI 用 `HIKARI_MAX_POOL_SIZE=3` 重启服务单独跑 capacity;为什么不 skip、不改弱断言;小池只是测试设定 | `application.yml` hikari、`.github/scripts/start-service.sh`、`test_capacity.py` |
