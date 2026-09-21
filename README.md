# ticket-qa — 智能客服工单系统 · 质量保障工程

一个含 LLM 依赖路径的工单服务(Spring Boot 3 / Java 17 / MyBatis-Plus / MySQL 8 / Redis 7 / RabbitMQ / WireMock),
以及围绕它建立的完整质量体系:单测与切片、接口与安全自动化、JMeter 压测与故障注入、CI 门禁、质量数据平台。
每一个非显然的技术决策都有一条决策记录(ADR),每一个测出来的问题都有一条可复现的记录(findings)。

## 0. 项目总览

### 0.1 被测服务做什么

工单从创建到关闭的六态状态机(`PENDING → ASSIGNED → PROCESSING → WAIT_CONFIRM → CLOSED`,外加 `ESCALATED`),
坐席抢单 / 组长指派、SLA 超时自动升级、状态变更审计、RabbitMQ 事件通知(消费端幂等)、附件上传三层校验、
三种角色的越权控制;创建时由 LLM 自动分类 + 定优先级,坐席回复时由 LLM 生成草稿——LLM 是一个输出不确定、
会超时、会越界的依赖,超时降级、熔断、契约校验、每次调用落盘是这条路径的核心。

### 0.2 架构

```
                       ┌──────────────────────────── 宿主(Windows / Linux) ────────────────────────────┐
  pytest / JMeter ───► │  service :8080   Spring Boot 单体                                                │
  curl / 平台导入      │   ├─ Controller(参数绑定)──► Service(权限 · 状态机 · 审计 · 事务边界)          │
                       │   │      │                        │            │                                 │
                       │   │      ▼                        ▼            ▼                                 │
                       │   │  LlmService ──► LlmClient ──┐   MyBatis-Plus    ApplicationEvent            │
                       │   │  (超时 3s / 熔断 5×60s /     │   (@Version 乐观锁)   AFTER_COMMIT ──► RabbitTemplate
                       │   │   契约校验 / 规则降级)       │                                                │
                       │   └─ SlaScanner(30s,Redis 锁 fail-open,条件 UPDATE)                          │
                       │  platform :8081  执行记录 / 趋势 / 性能基线对比(Vue 静态页 + 4 个接口)           │
                       └───────┬──────────────┬───────────────┬──────────────┬──────────────┬────────────┘
                               ▼              ▼               ▼              ▼              ▼
   docker compose         MySQL 8         Redis 7        RabbitMQ 3     WireMock 3      Prometheus
   (ops/)                 ticket 表 ×6    坐席缓存        3 队列 ×       LLM 挡板         抓 /actuator
                          + qa_ 表 ×2     抢单 / SLA 锁   幂等消费者     [SLOW]/[ERROR]   /prometheus
```

- 状态机数据驱动(枚举 + 迁移表),Service 层拦非法流转(ADR-001);状态变更与审计同事务,MQ 在提交后发(ADR-002)。
- 抢单三层防线:Redis 前置锁削峰(fail-open)→ 条件 UPDATE 根治 → `version` 乐观锁兜底(ADR-016);审计 `from_status` 只在 UPDATE 命中后写(ADR-017)。
- LLM 路径:`LlmClient` 双实现(真实 / WireMock 挡板),同一层韧性外壳;挡板靠标题里的故障标记制造超时、500、越界、坏 JSON(ADR-004 / 009)。
- 所有决策:[`docs/adr/`](docs/adr/README.md)(23 条);逐模块讲解:[`docs/walkthrough.md`](docs/walkthrough.md)。

### 0.3 质量体系全景

| 层 | 在哪 | 数量 / 手段 | 回答什么问题 |
|---|---|---|---|
| 单测 + 切片 | `service/src/test/java` | 330 次执行:JUnit 5 + Mockito;H2 切片跑真 SQL(条件更新、乐观锁、闭区间);`@WebMvcTest` 测 HTTP 边界 | 每个边界是否被精确打到(毫秒 / 字节 / 第 N 次) |
| 接口 + 安全自动化 | `tests/api`、`tests/security` | 312 次执行:pytest + requests 自研四层封装;直连 MySQL / WireMock / RabbitMQ / 指标做旁路断言;Allure | 每条链路在真容器上是否真的通,包括接口看不见的部分 |
| 并发 / 容量 / 故障注入 | `tests/api/test_concurrency.py`、`test_capacity.py`、`test_fault_injection.py` | 栅栏同步多线程、审计序列反向断言、`docker compose stop` 注入 | 竞态是否回归;积压能否清空;依赖恢复多久回到正常 |
| 压测与取证 | `tests/perf` | JMeter 4 条链路 + 环境状态强制落盘 + 取证 SQL + Arthas 手册 | 拐点在哪、瓶颈在哪一层、数字是否可复现 |
| 覆盖率与 CI | `.github/workflows/ci.yml` | JaCoCo 全量兜底 70/60 + diff-cover 增量 80%;compose 起环境 → 预热连接池 → pytest → Allure 归档 | 改坏了会不会自动响 |
| 质量数据平台 | `platform/` | 执行记录、通过率 / 覆盖率趋势、性能基线对比(带环境状态,不可比即降级) | 这次比上次退化了吗——以及这个比较可不可信 |
| 记录 | `docs/findings/` | 联调发现、压测 5 篇、故障注入、修复后回归、已知问题 KI-001~017 | 测出来的每一个问题:现象、根因、证据、处置 |

从压测到修复的闭环(2026-09-20 → 09-21):抢单 2 线程即 100% 重复分配 → 定位到 check-then-act + 连接池状态漂移 →
修复后用同样手段回归 2×5 / 20 / 100 线程及 Redis 停机下恰好 1 个成功 → 并发用例进 CI 门禁 → 平台把"环境不同的对比不可信"自动化。
完整记录:[`docs/findings/修复后回归验证.md`](docs/findings/修复后回归验证.md)。

### 0.4 怎么复现全部测试(一次过的顺序)

```bash
# 0. 基础设施(Docker;Windows 无 Docker Desktop 的路线见 §1)
cd ops && cp .env.example .env && docker compose up -d && cd ..
bash ops/smoke/cold_start.sh                 # 可选:删卷重建 + 冒烟,13 秒全部 healthy

# 1. 单测 + 覆盖率(不需要容器,约 30 秒)
cd service && mvn -B verify && cd ..         # 330 个,JaCoCo 报告 service/target/site/jacoco/index.html

# 2. 起服务
cd service && java -Dfile.encoding=UTF-8 -jar target/ticket-qa-service-0.1.0.jar & cd ..     # 等 /actuator/health 为 UP;Windows 上 -Dfile.encoding 不能省(§3)

# 3. 接口 + 安全 + 并发 + 容量 + 故障注入(约 7 分钟;故障注入需要 tests/api/config/*.env 里的 DOCKER_COMPOSE_CMD)
cd tests && pip install -r requirements.txt && python tools/warm_pool.py && python -m pytest && cd ..
# 预期:全部 passed,3 xfailed(KI-001 / KI-002),0 failed;allure serve tests/allure-results 看报告
# 容量用例(-m capacity)要求池被打满:服务端很快的机器上请用小池起服务再跑(CI 就是这么跑的,ADR-023)
#   HIKARI_MAX_POOL_SIZE=3 java -Dfile.encoding=UTF-8 -jar service/target/ticket-qa-service-0.1.0.jar &  →  cd tests && python tools/warm_pool.py && python -m pytest -m capacity

# 4. 压测(JMeter 5.6,tests/perf/README.md;JDK / JMeter / python 路径填在 tests/perf/tools/local.env,见 local.env.example)
cd tests/perf && bash tools/regress_grab.sh fix && bash tools/run_load.sh grab_throughput.jmx 50 grab_t50 20 && cd ../..

# 5. 平台:导入 + 看趋势与基线对比
cd platform && mvn -B -DskipTests package && java -jar target/ticket-qa-platform-0.1.0.jar & cd ..   # http://localhost:8081
python tests/perf/tools/to_platform.py grab_t50 --post --baseline
python tests/tools/publish_run.py --suite unit --junit "service/target/surefire-reports/TEST-*.xml" --jacoco service/target/site/jacoco/jacoco.xml --post
```

CI(`.github/workflows/ci.yml`)按同样顺序跑 1 → 3,push / PR 到 main 触发。

```
ticket-qa/
├── service/        Spring Boot 被测服务(mvn 构建);src/test/java 是 JUnit 5 + Mockito + H2 切片
├── platform/       质量数据平台(Spring Boot :8081 + Vue 静态页),导入格式见 platform/README.md
├── ops/            docker-compose、MySQL 初始化 SQL 与迁移、WireMock 桩、Prometheus 配置、联调冒烟脚本、WSL 说明
├── docs/           adr(23 条)/ walkthrough / test-design(8 篇)/ test-inventory / findings(压测、故障注入、回归、已知问题)
├── tests/          api(pytest 接口自动化 + 自研封装)/ security(越权、注入、绕过)/ perf(JMeter + 取证工具)/ tools
└── .github/        workflows/ci.yml:编译 → 单测 → 覆盖率门禁 → 起环境 → 预热连接池 → 接口自动化 → Allure 归档
```

---

## 1. 环境准备

| 工具 | 版本 | 说明 |
|---|---|---|
| Docker + Compose v2 | 任意近期版本 | 跑 MySQL / Redis / RabbitMQ / WireMock / Prometheus |
| JDK | 17 | Temurin 17 验证过 |
| Maven | 3.9.x | 国内建议在 `conf/settings.xml` 加阿里云镜像 `https://maven.aliyun.com/repository/public` |
| Python | 3.10+ | 接口自动化、压测工具、平台导入脚本;服务本身不需要 |
| JMeter | 5.6.x | 只有压测需要 |

### Windows 上没有 Docker Desktop 时(本项目联调采用的方式)

Docker Desktop 需要管理员权限。替代路线:WSL2 + Ubuntu + Docker Engine,全程用户态。
完整步骤、三层存活机制的解释、试过不奏效的方案,都在 [`ops/wsl/README.md`](ops/wsl/README.md);
一句话版本:

```powershell
wsl --install -d Ubuntu-24.04 --web-download --no-launch
wsl -d Ubuntu-24.04 -u root -- bash ops/wsl/wsl-docker-setup.sh      # 在仓库根目录执行;wsl 会把当前目录映射到 /mnt/<盘符>/…
Copy-Item ops\wsl\wslconfig.example $env:USERPROFILE\.wslconfig          # 虚拟机不自动关机
Copy-Item ops\wsl\wsl-keepalive.vbs ([Environment]::GetFolderPath('Startup'))   # 发行版不自动终止
wscript.exe ops\wsl\wsl-keepalive.vbs; wsl --shutdown
```

关键事实:**WSL 在最后一个 `wsl.exe` 会话退出后几秒就终止发行版**(systemd 服务和 `[boot] command`
都不算会话),容器随之消失、Windows 侧 `Connection refused`。启动文件夹里的 `wsl-keepalive.vbs`
挂一个隐藏会话解决它;compose 各服务的 `restart: unless-stopped` 负责发行版重启后把容器拉回来。

## 2. 起基础设施

```bash
cd ops
cp .env.example .env          # 端口和密码都在这里,默认值与 application.yml 一致,可直接用
docker compose up -d
docker compose ps             # 等 mysql / rabbitmq / redis / wiremock 都变成 healthy
```

首次启动 MySQL 会执行 `ops/mysql/init/*.sql` 建表 + 灌 6 个坐席。**这只在数据卷为空时执行一次**;
改了 SQL 想重建:`docker compose down -v && docker compose up -d`,或直接跑
`bash ops/smoke/cold_start.sh`(删卷 → 重建 → 等 healthy → 核对表数 / 坐席数 / 字符集 / 桩数量)。
2026-09-20 / 09-21 各做过一次完整冷启动:`down -v` 后十几秒全部 healthy,冒烟脚本一次全绿。

**已有数据卷升级到 v0.4**(`ticket` 表加了乐观锁列 `version`,ADR-016):不想删卷就执行一次迁移
`ops/mysql/migrations/V2__ticket_version.sql`(用法写在文件头);新卷由 `init/01-schema.sql` 直接建出。
平台的两张 `qa_` 表由平台自己在启动时建,不依赖初始化脚本。

各组件入口(默认端口):

| 组件 | 地址 | 账号 |
|---|---|---|
| MySQL | `localhost:3306` 库 `ticket_qa` | `ticketqa / ticketqa123` |
| Redis | `localhost:6379` | 密码 `redis123` |
| RabbitMQ 管理台 | http://localhost:15672 | `ticketqa / rabbit123` |
| WireMock 管理 API | http://localhost:8089/__admin/mappings | — |
| Prometheus | http://localhost:9090 | — |

## 3. 跑服务

```bash
cd service
mvn spring-boot:run
# 或
mvn -DskipTests package && java -Dfile.encoding=UTF-8 -jar target/ticket-qa-service-0.1.0.jar
```

启动成功的标志:日志里 `Started TicketQaApplication`,`curl localhost:8080/actuator/health`
返回 `"status":"UP"` 且 db / redis / rabbit 都 UP。

Windows + JDK 17 的 `-Dfile.encoding=UTF-8` 不能省:JDK 17 的默认字符集跟系统走(中文 Windows 是 GBK),
文件日志 `service/logs/ticket-qa-service.log` 会按 GBK 写,两条按中文关键字读文件日志的用例
(`test_file_log_carries_trace_id`、`test_publish_failure_is_observable_and_not_replayed`)就会读不到。CI(Linux)和 JDK 18+ 默认就是 UTF-8。

服务读取的环境变量(全部有默认值,与 `ops/.env.example` 对齐):
`MYSQL_HOST/PORT/DATABASE/USER/PASSWORD`、`REDIS_HOST/PORT/PASSWORD`、`RABBITMQ_HOST/PORT/USER/PASSWORD`、
`WIREMOCK_BASE_URL`、`LLM_MODE`、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`、`APP_ATTACHMENT_DIR`、`APP_TIME_ZONE`。

可选:把服务也放进 compose——`docker compose --profile app up -d --build`(用 `service/Dockerfile` 多阶段构建)。

## 4. LLM:挡板 与 真实调用 怎么切

| | `LLM_MODE=mock`(默认) | `LLM_MODE=real` |
|---|---|---|
| 实现类 | `WireMockLlmClient` | `OpenAiCompatibleLlmClient` |
| 目标 | WireMock 容器 `http://localhost:8089` | `${LLM_BASE_URL}/chat/completions`,默认 DeepSeek |
| 需要 | 容器起着 | `LLM_API_KEY`;OpenAI 要把 `LLM_BASE_URL` 设成 `https://api.openai.com/v1` |
| 没 key 会怎样 | — | 启动打 WARN,调用得到 401 → `UPSTREAM_ERROR` → 走关键词规则,服务不挂 |

两种模式共用同一层超时 / 熔断 / 契约校验 / 落盘(`LlmService`),切换只影响 HTTP 目标。

**挡板的故障开关**(写在工单标题里,`ops/wiremock/mappings/`):

| 标题含 | 挡板行为 | 服务侧结果 |
|---|---|---|
| `[SLOW]` | 延迟 5 秒 | 3 秒超时 → `degraded=true reason=TIMEOUT` → 规则分类 |
| `[ERROR]` | HTTP 500 | `UPSTREAM_ERROR` → 规则;连续 5 次后熔断 60 秒(`CIRCUIT_OPEN`) |
| `[BAD_CATEGORY]` | 返回 `SPAM` | 契约越界 → `category=OTHER`,`llm_contract_violation_total` +1 |
| `[BAD_JSON]` | 返回非 JSON | `BAD_RESPONSE` → 规则 |
| 退款 / 账单 / 报错 等关键词 | REFUND / BILLING / TECH | 正常分类 |
| 其他 | OTHER / P2 | 正常分类 |

## 5. 接口清单

鉴权只认请求头 `X-User-Id`(种子坐席见下表),没有密码——这是测试系统不是生产系统(ADR-007)。

| X-User-Id | 用户 | 角色 | 组 |
|---|---|---|---|
| 1 | admin | ADMIN | 1 |
| 2 | leader_1 | LEADER | 1 |
| 3 | agent_a | AGENT | 1 |
| 4 | agent_b | AGENT | 1 |
| 5 | leader_2 | LEADER | 2 |
| 6 | agent_c | AGENT | 2 |

所有响应都是 `{"code","message","data","traceId"}`,`code=0` 成功;错误码前三位即 HTTP 状态
(`40901` → 409),完整列表在 `common/ErrorCode.java`。响应头 `X-Trace-Id` 可用来对日志(文件日志同样带 traceId)。
写接口都带乐观锁:读到的 `version` 已过期时返回 409 / 40903,刷新后重试(ADR-016 / 017)。

| 方法 | 路径 | 说明 | 谁能调 |
|---|---|---|---|
| GET | `/api/agents/me` | 当前用户 | 任何已认证 |
| POST | `/api/tickets` | 创建工单,触发 LLM 分类 + 优先级,算 SLA 截止 | 任何已认证 |
| GET | `/api/tickets/{id}` | 详情 | AGENT 本人单 / LEADER 本组 / ADMIN |
| GET | `/api/tickets?status=&page=&size=` | 列表,按角色自动收窄 | 任何已认证 |
| PUT | `/api/tickets/{id}` | 改标题 / 内容(已关闭不可改) | 同详情的写权限 |
| DELETE | `/api/tickets/{id}` | 逻辑删除 | ADMIN |
| POST | `/api/tickets/{id}/transitions` | 状态流转 `{"target","assigneeId?","remark?"}` | 写权限;target=ASSIGNED 需 LEADER/ADMIN |
| POST | `/api/tickets/{id}/grab` | 抢单(PENDING → ASSIGNED 给自己);失败 409:40901 已被抢 / 40904 正在被抢(Redis 前置锁) | 本组任何人 |
| POST | `/api/tickets/{id}/assign` | 指派 / 改派 `{"assigneeId","remark?"}` | LEADER 本组 / ADMIN |
| GET | `/api/tickets/{id}/audit-logs` | 审计轨迹 | 读权限 |
| POST | `/api/tickets/{id}/reply-draft` | LLM 生成回复草稿 | 写权限 |
| POST | `/api/tickets/{id}/attachments` | 上传附件,multipart 字段 `file` | 写权限 |
| GET | `/api/tickets/{id}/attachments` | 附件列表 | 读权限 |
| POST | `/api/admin/sla/scan` | 手动触发一轮 SLA 扫描,返回升级数 | ADMIN |
| GET | `/actuator/health` `/actuator/prometheus` | 健康、指标 | 无需认证 |

### curl 走一遍(Windows 请在 Git Bash 里跑,PowerShell 的 curl 是别名)

```bash
H='Content-Type: application/json'
# 创建 → LLM 分类
curl -s -X POST localhost:8080/api/tickets -H "$H" -H 'X-User-Id: 1' \
  -d '{"title":"申请退款","content":"订单重复扣款","customerId":1001}'
# 抢单(agent_a)→ 状态 ASSIGNED,assigneeId=3
curl -s -X POST localhost:8080/api/tickets/1/grab -H 'X-User-Id: 3'
# 水平越权:agent_b 看 agent_a 的单 → 403 / 40301
curl -s localhost:8080/api/tickets/1 -H 'X-User-Id: 4'
# 垂直越权:agent 改派 → 403 / 40302
curl -s -X POST localhost:8080/api/tickets/1/assign -H "$H" -H 'X-User-Id: 3' -d '{"assigneeId":4}'
# 流转:ASSIGNED → PROCESSING;非法流转 → 409 / 40901
curl -s -X POST localhost:8080/api/tickets/1/transitions -H "$H" -H 'X-User-Id: 3' -d '{"target":"PROCESSING"}'
curl -s -X POST localhost:8080/api/tickets/1/transitions -H "$H" -H 'X-User-Id: 3' -d '{"target":"CLOSED"}'
# 审计
curl -s localhost:8080/api/tickets/1/audit-logs -H 'X-User-Id: 3'
# 回复草稿
curl -s -X POST localhost:8080/api/tickets/1/reply-draft -H 'X-User-Id: 3'
# 附件:必须显式给 type,application/octet-stream 会被拒(ADR-008)
curl -s -X POST localhost:8080/api/tickets/1/attachments -H 'X-User-Id: 3' -F 'file=@photo.png;type=image/png'
curl -s -X POST localhost:8080/api/tickets/1/attachments -H 'X-User-Id: 3' -F 'file=@shell.php;filename=shell.jpg;type=image/jpeg'   # 415 / 41503
# 降级路径
curl -s -X POST localhost:8080/api/tickets -H "$H" -H 'X-User-Id: 1' -d '{"title":"[SLOW] 退款","content":"x","customerId":1}'
# SLA 手动扫描
curl -s -X POST localhost:8080/api/admin/sla/scan -H 'X-User-Id: 1'
```

Windows 控制台里中文乱码是终端编码问题(GBK),不影响服务;用 `ops/smoke/smoke_api.py`
(UTF-8 输出)可以一次跑完上面全部路径并断言。

## 6. 怎么确认"链路通了"

| 要确认的 | 看哪里 |
|---|---|
| 创建工单触发了 LLM 分类 | 响应里 `category / priority`;`llm_call_log` 表每次调用一行(`request_model / response_model / latency_ms / degraded / degrade_reason`);WireMock `GET /__admin/requests` 能看到请求 |
| 状态流转落了审计 | `GET /api/tickets/{id}/audit-logs`,或 `ticket_audit_log` 表:谁、何时、从哪到哪、`source`(MANUAL / SCHEDULER / LLM)、traceId |
| 抢单改了状态 | 响应 `status=ASSIGNED assigneeId=你`;再抢 → 409;指标 `grab_lock_{acquired,rejected,unavailable}_total`、`grab_conflict_total`、`ticket_version_conflict_total` 说明三层防线各拦了多少 |
| MQ 消息被消费 | `mq_message_dedup` 表(每条消息每个消费者一行);服务日志 `[通知客户] / [通知坐席] / [通知组长]`;指标 `mq_event_published_total == mq_event_consumed_total`;RabbitMQ 管理台队列 `q.ticket.*` 消息数为 0 |
| MQ 重复投递被去重 | 管理台向交换机 `ticket.events` 重发同一 `messageId` 的消息 → `mq_event_duplicate_total` +1,去重表不新增 |
| SLA 自动升级 | `UPDATE ticket SET sla_deadline = NOW(3) WHERE id=?` 后 `POST /api/admin/sla/scan` → 状态 ESCALATED、审计 `source=SCHEDULER`、`sla_escalated_total` +1;再扫一次 → 0(不重复) |
| 附件能传、绕过被拦 | 合法 png/txt → 201,文件落在 `service/data/attachments/<uuid>.<ext>`;php / 改名 / octet-stream / 双扩展名 → 415,`>5MB` → 413 |
| 越权被拦 | 水平 403 + 40301,垂直 403 + 40302,未认证 401 + 40101 |
| 熔断 | 5 次 `[ERROR]` 后 `llm_circuit_state=1`、`llm_circuit_open_total=1`,之后的调用 `degrade_reason=CIRCUIT_OPEN`,60 秒后自动恢复 |

`ops/smoke/smoke_api.py`、`smoke_links.py`、`smoke_faults.py` 把上面全部走一遍并断言(联调工具,不是测试体系)。
联调时发现的一个典型问题——所有 LLM 调用在静默降级、接口层面看不出来——完整记录在
[`docs/findings/20260920-联调发现-h2c升级导致LLM静默降级.md`](docs/findings/20260920-联调发现-h2c升级导致LLM静默降级.md)。

## 7. 常见启动问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `Communications link failure` / `Connection refused` 连 MySQL | 容器没起、还没 healthy、或 WSL 发行版因为没有会话被终止了 | `docker compose ps`;`wsl -l -v` 若是 Stopped,跑 `wscript.exe ops\wsl\wsl-keepalive.vbs`,见 `ops/wsl/README.md` |
| MySQL 起了但没有表 / 坐席 | init SQL 只在数据卷为空时跑 | `docker compose down -v` 再 `up -d` |
| 坐席 `displayName` 是乱码 | 每个 init SQL 文件是独立会话,必须各自 `SET NAMES utf8mb4` | 已修;重建数据卷 |
| LLM 调用全部 `UPSTREAM_ERROR: RST_STREAM / EOF reached`,分类却"看起来正常" | JDK HttpClient 默认发 `Upgrade: h2c`,叠加 Spring 的 chunked 请求体,WireMock/Jetty 丢掉请求体;降级到规则把问题盖住了 | 已修(`LlmClientConfig` 强制 HTTP/1.1);复现程序 `ops/smoke/H2cRepro.java`;详见 findings |
| 3 秒超时被记成 `UPSTREAM_ERROR` 而不是 `TIMEOUT` | Spring `JdkClientHttpRequest` 抛的是 `java.util.concurrent.TimeoutException` | 已修(`LlmHttpSupport` 识别三种超时异常) |
| `updated_at` 永远等于创建时间 | MyBatis-Plus `strictUpdateFill` 只填 null 字段 | 已修(`MybatisPlusConfig` 用 `setFieldValByName`) |
| RabbitMQ 报 `PRECONDITION_FAILED - inequivalent arg` | 改了队列 / 交换机的声明参数(durable 等),Broker 上还是旧的 | 管理台删掉队列,或 `docker compose down -v` |
| Redis `NOAUTH` / `WRONGPASS` | `.env` 的 `REDIS_PASSWORD` 和 `application.yml` 默认值不一致 | 二者对齐,或通过环境变量传给服务 |
| 端口 8080 / 3306 被占 | 本机已有服务 | 改 `.env` 端口并通过环境变量告诉服务 |
| `mvn` 下载依赖极慢 | 直连 Maven Central | Maven `settings.xml` 加阿里云镜像 |
| 上传附件 415 `application/octet-stream` | 客户端没声明 Content-Type | curl 加 `;type=image/png`;这是有意的(ADR-008) |
| Windows 控制台中文乱码 | 终端 GBK | `chcp 65001` 或用 Python 脚本;服务本身是 UTF-8 |
| 文件日志里中文乱码、`test_file_log_carries_trace_id` 失败 | JDK 17 在 Windows 上默认字符集是 GBK,logback 文件日志按它写 | `java -Dfile.encoding=UTF-8 -jar …`(§3) |

## 8. 指标

`GET /actuator/prometheus`。自定义指标一览在 `docs/walkthrough.md` 第 13 节。
Prometheus 容器按 `ops/prometheus/prometheus.yml` 每 10 秒抓 `host.docker.internal:8080`。
Grafana 看板不在仓库里:指标已按 Prometheus 格式暴露,面板按需自配。

## 9. 故障注入

```bash
docker compose stop wiremock    # LLM 不可用 → 分类走规则,llm_fallback_total 涨,5 次后熔断
docker compose stop rabbitmq    # 状态变更仍成功,mq_event_publish_failed_total 涨(消息丢失,ADR-002)
docker compose stop redis       # 鉴权仍可用但每次请求多 ~1s(两次缓存操作各等 500ms 超时后回源查库),SLA 扫描 fail-open 继续跑,/actuator/health 503
docker compose start <服务>     # 恢复
```

2026-09-20 的手动注入结果在 `docs/findings/20260920-故障注入记录.md`;`tests/api/test_fault_injection.py` 把 RabbitMQ / Redis 两个场景
自动化了(需要 `tests/api/config/*.env` 里的 `DOCKER_COMPOSE_CMD`),恢复时长的 SLO 在 ADR-020,MQ 消息丢失的决定在 ADR-018。
观察其它场景按 `docs/findings/故障注入记录模板.md` 记录。

## 10. 跑测试

### 单测(不需要任何容器)

```bash
cd service
mvn -B verify          # 330 个单测 + JaCoCo 报告 target/site/jacoco/index.html + 全量兜底线(行 70% / 分支 60%)
```

Mockito 测编排,H2 内存库跑手写 SQL(闭区间、条件更新、乐观锁),`@WebMvcTest` 测 HTTP 边界(ADR-013)。约 30 秒。

### 接口自动化 + 安全用例(需要 §2 的容器 + §3 的服务)

```bash
cd tests
pip install -r requirements.txt
python tools/warm_pool.py              # 把 HikariCP 撑到上限,并发用例才可复现(ADR-021;CI 里也是这一步)
python -m pytest                       # 312 条,约 7 分钟(熔断 2 分钟 + 故障注入 2 分钟排在最后)
python -m pytest -m "not circuit and not fault and not capacity"   # 只跑功能 + 安全,约 3 分钟
python -m pytest -m capacity -q             # 容量用例;前提"池被打满"由小池构造:服务以 HIKARI_MAX_POOL_SIZE=3 起(ADR-023)
python -m pytest -m concurrency -q     # 竞态回归门禁(抢单 / 指派 / 流转的并发)
python -m pytest api/test_sla.py -q    # 只跑一个文件
python -m pytest -m known_issue -q     # 只看已知问题(xfail)
```

环境用 `TICKETQA_ENV=local`(默认)/ `ci` 选 `tests/api/config/*.env`,真实环境变量优先。
用例直连 MySQL 做旁路断言和清理(每个用例硬删自己造的工单),需要 `ops/.env` 里的账号;
`fault` 用例还要 `DOCKER_COMPOSE_CMD`(Docker 在 WSL2 里时的写法见 `local.env`),没配就整体 skip 并说明原因。
预期结果:全部 passed + 3 条 xfailed(KI-001 / KI-002,见 `docs/findings/known-issues.md`),0 failed。
标记:`smoke / llm / circuit / slow / security / db / mq / known_issue / concurrency / capacity / fault`(`tests/pytest.ini`)。

### Allure 报告

```bash
cd tests
python -m pytest                                   # 结果落在 tests/allure-results/
allure serve allure-results                        # 需要 Allure CLI(Java);或 allure generate allure-results -o allure-report --clean
```

每个请求 / 响应是附件,每个断言是 step;按 feature(状态机 / SLA / LLM 路径 / MQ / 附件 / 安全)分组。
CI 里同样的报告作为 artifact `allure-report` 归档 30 天。

### 压测与竞态回归(JMeter)

`tests/perf/README.md`:四条链路(抢单集合点、抢单吞吐、工单创建、读链路)、参数说明、`run_load.sh`(每轮强制落盘环境状态)、
`regress_grab.sh`(竞态回归)、`ladder_full.sh`(全梯度)。已跑过的结果与结论:`docs/findings/20260920-压测-*.md`、`修复后回归验证.md`。

### 质量数据平台

`platform/README.md`:起、导入格式(`POST /api/runs`、`POST /api/perf-runs`)、对比接口。
`tests/perf/tools/to_platform.py <tag> --post` 导一轮压测,`tests/tools/publish_run.py --suite … --junit … --post` 导一次执行。

### CI

`.github/workflows/ci.yml`,push / PR 到 main 触发:`unit`(编译 + 单测 + JaCoCo + diff-cover 增量门禁 80%)→
`api`(compose 起中间件 → java -jar 起服务 → 预热连接池 → pytest 含并发 / 故障注入 → 用 `HIKARI_MAX_POOL_SIZE=3` 重启服务、只跑 capacity → 两部分合成一份 Allure 归档)。
阈值和编排的理由在 ADR-011 / ADR-015 / ADR-021;容量用例为什么单独一步、为什么用小池在 ADR-023。

