# CLAUDE.md — 智能客服工单系统 · 质量保障工程

本文件是仓库的规格与约束:技术栈、目录、业务规格、代码与提交规范。章节编号被代码注释和文档大量引用
(`CLAUDE.md §5.1` 等),不要重排。

## 0. 项目简介

一个含 LLM 依赖路径的工单服务,以及为它建立的质量保障体系。服务是 Spring Boot 单体:
工单状态机、坐席抢单与指派、SLA 超时自动升级、RabbitMQ 事件通知(消费端幂等)、附件上传、
三种角色的越权控制;工单创建时由 LLM 自动分类并预测优先级,坐席回复时由 LLM 生成草稿,
LLM 超时降级、连续失败熔断、返回值契约校验、每次调用落盘。

质量体系覆盖:JUnit 5 + Mockito 单测与 H2 / WebMvc 切片、pytest 接口与安全自动化(自研封装)、
JMeter 压测与故障注入、JaCoCo / coverage.py 覆盖率门禁、GitHub Actions CI、极简质量数据平台。

## 1. 文档地图

| 想知道 | 看 |
|---|---|
| 为什么这么设计 | `docs/adr/`(每条固定五节:背景 / 选项 / 决定 / 后果 / 常见质疑与回应) |
| 代码怎么读 | `docs/walkthrough.md`(逐模块,Java / Spring 层面) |
| 用例怎么来的 | `docs/test-design/`、`docs/test-inventory.md` |
| 测出来的问题与实测数据 | `docs/findings/`(只写真实跑出来的结果) |
| 怎么起、怎么跑全部测试 | `README.md`、`tests/perf/README.md`、`platform/README.md` |

## 2. 怎么跑

见 `README.md` §0.4:compose 起中间件 → `mvn verify` → `java -jar` → `pytest` → JMeter → 平台导入。

## 3. 技术栈

| 层 | 选型 |
|---|---|
| 被测服务 | Spring Boot 3.x + Java 17 |
| 持久层 | MyBatis-Plus + MySQL 8 |
| 缓存 | Redis 7 |
| 消息队列 | RabbitMQ |
| 构建 | Maven |
| 单元测试 | JUnit 5 + Mockito |
| 接口自动化 | Python + pytest + requests(自研封装,不用 HttpRunner) |
| Mock 挡板 | WireMock |
| 性能测试 | JMeter |
| 覆盖率 | JaCoCo + coverage.py |
| CI | GitHub Actions |
| 指标 | Actuator + Micrometer,暴露 Prometheus 格式端点 |
| 平台层 | Spring Boot + Vue(极简,CDN 引入,无构建) |
| 本地编排 | docker-compose |

架构:**单体**。不拆微服务,不引入 Nacos / Gateway / Sentinel / Jenkins / ELK / Loki / SkyWalking / K8s。
Grafana 看板不在仓库内,只暴露指标。故障注入用 `docker compose stop / start`,不引入 ChaosBlade。

## 4. 目录结构

```
ticket-qa/
├── CLAUDE.md              本文件:规格与约束
├── docs/
│   ├── adr/               决策记录(背景 / 选项 / 决定 / 后果 / 常见质疑与回应)
│   ├── walkthrough.md     逐模块讲解(Java / Spring 层面)
│   ├── test-design/       用例设计(状态迁移、边界值、判定表、等价类、场景法)
│   ├── test-inventory.md  全部用例清单
│   └── findings/          实测记录:联调、压测、故障注入、回归、已知问题
├── service/               Spring Boot 被测服务;单测在 src/test/java
├── tests/
│   ├── api/               pytest 接口自动化(framework/ 是自研封装)
│   ├── security/          越权、注入、绕过用例
│   ├── perf/              JMeter 脚本与压测取证工具
│   └── tools/             连接池预热、执行结果发布
├── platform/              质量数据平台(执行记录 / 趋势 / 性能基线对比)
├── ops/                   docker-compose、MySQL 初始化与迁移 SQL、WireMock 桩、Prometheus 配置、冒烟脚本
└── .github/workflows/     CI
```

## 5. 业务规格

### 5.1 工单状态机

状态:`PENDING` `ASSIGNED` `PROCESSING` `WAIT_CONFIRM` `CLOSED` `ESCALATED`

合法流转(**其余一律非法,Service 层拦截抛 `IllegalTransitionException`**):

```
PENDING      → ASSIGNED | ESCALATED
ASSIGNED     → PROCESSING | PENDING(退回) | ESCALATED
PROCESSING   → WAIT_CONFIRM | ESCALATED
WAIT_CONFIRM → CLOSED | PROCESSING(用户不认可)
CLOSED       → PROCESSING(重开,限 7 天内,闭区间)
ESCALATED    → ASSIGNED
```

状态机**数据驱动**(枚举 + 迁移表),不用 if-else 堆砌;迁移表是用例推导的依据(ADR-001,test-design/01)。

### 5.2 坐席抢单

`POST /api/tickets/{id}/grab`:本组任何人可抢 `PENDING` 单,成功后 `ASSIGNED` 且 `assignee` 为自己。
并发下同一张单只能被一个人抢到:Redis 前置锁削峰(fail-open)、条件 UPDATE(`WHERE status='PENDING' AND version=?`)
保证正确性、`version` 乐观锁覆盖所有写路径;失败方 409(40901 / 40903 / 40904)。决策与验证见 ADR-016、findings/修复后回归验证。

### 5.3 SLA 与自动升级

响应时限:P0 = 15 分钟,P1 = 60 分钟,P2 = 240 分钟。计时起点为工单创建时刻;超时仍未进入 `PROCESSING`
则自动转 `ESCALATED` 并发 MQ 通知。定时任务扫描,同一工单不能被升级两次(条件 UPDATE)。
边界按**闭区间**:恰好等于时限即算超时(ADR-006)。

### 5.4 异步链路

走 RabbitMQ 的事件:状态变更通知、SLA 升级通知、分配通知。消费端幂等,用 MySQL 消息去重表实现(ADR-003)。
事务提交后发送;Broker 不可用期间的消息丢失可观测(计数 + ERROR 日志),不补投(ADR-002 / ADR-018)。

### 5.5 LLM 依赖路径

两个调用点:工单创建时自动分类(`BILLING` `TECH` `REFUND` `OTHER`)+ 优先级预测(P0 / P1 / P2);坐席回复时生成回复草稿。

契约:返回分类必须在枚举内,越界 → 计数打点并落到 `OTHER`;超时阈值 3 秒 → 降级走关键词规则;
连续失败 5 次 → 熔断 60 秒(定值,不探测),期间直接走规则;每次调用落盘:请求模型名、响应模型名、耗时、是否降级;
指标 `llm_fallback_total`、`llm_circuit_open_total`(带标签的计数启动即预注册为 0)。

所有调用走统一 `LlmClient` 接口,两个实现:真实调用 + WireMock 挡板;接口自动化默认走挡板。

### 5.6 权限模型

角色:`AGENT` `LEADER` `ADMIN`。AGENT 只能读写分配给自己的工单;LEADER 能读本组全部工单、能改派;ADMIN 全权。
越权校验放 Service 层,不只在 Controller 拦(ADR-007)。

### 5.7 附件

白名单 `jpg / png / pdf / txt`,单文件 ≤ 5MB,存本地目录,文件名重命名为 UUID;同时校验扩展名、声明 MIME 与文件魔数(ADR-008)。

### 5.8 审计日志

每次状态变更落一条:谁、何时、从什么状态到什么状态、操作来源(人工 / 定时任务 / LLM)。
`from_status` 只在 UPDATE 命中 1 行后写,保证等于写时刻的真实前值;同一工单的审计序列必须首尾相接(ADR-017)。

## 6. 代码规范

- 统一异常处理 `@RestControllerAdvice`,业务异常有明确错误码(前三位即 HTTP 状态)
- 参数校验用 Bean Validation 注解,不在方法体里手写判空
- 接口统一返回 `Result<T>`,不裸返实体
- 时间字段用 `LocalDateTime`,时区在配置里显式声明
- 日志用 SLF4J,关键链路打 traceId(控制台与文件日志都带)
- 禁止 `e.printStackTrace()`
- `@Transactional` 显式写 `rollbackFor`,事务边界在 ADR 里说明;需要"事务外先做某事"的方法用 `TransactionTemplate`
- 每一个非显然的技术决策追加一条 ADR(固定五节);测出来的问题记进 `docs/findings/`,只写真实结果

## 7. 提交规范

- 一次提交一件事
- commit message 说明**为什么**,不只说做了什么
- 每个阶段结束打一个 tag(`v0.1-service`、`v0.2-tests`、`v0.3-perf`、`v0.4-fix` …)

## 8. 明确不做

微服务拆分、K8s、Jenkins、ELK / Loki、链路追踪、ChaosBlade、精美前端、未被要求的"未来扩展点"。
