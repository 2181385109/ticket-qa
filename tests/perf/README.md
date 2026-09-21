# tests/perf — JMeter 脚本模板

两条链路,只给脚本和参数,**不给结论**。跑出来的数据按 `docs/findings/压测记录模板.md` 记录。

| 脚本 | 链路 | 一句话 |
|---|---|---|
| `grab_race.jmx` | 抢单(竞态) | setUp 创建 1 张 PENDING 单 → N 个坐席线程在集合点同时 `POST /grab` → tearDown 取回终态和审计 |
| `grab_throughput.jmx` | 抢单(吞吐) | N 个线程持续抢**不同**的 PENDING 单(id 从 `results/ticket_ids.csv` 取、不回收),找抢单链路的拐点 |
| `ticket_create.jmx` | 工单创建 | N 个线程持续 `POST /api/tickets` 指定时长,标题从 `titles.csv` 轮询(决定挡板走哪条桩) |
| `ticket_read.jmx` | 读链路 + 修改 | 每线程循环 详情 GET → 列表 GET(status 过滤 + 分页 + COUNT)→ PUT 改标题,id 从 `idsCsv` 轮询;身份 `userId`(默认 ADMIN)、`listStatus`(默认 PENDING) |

2026-09-20 用这些脚本跑过一轮完整的压测 + 故障注入,结果与根因在 `docs/findings/20260920-压测-*.md`、`20260920-故障注入记录.md`,
用到的 Arthas 命令在 `docs/findings/arthas-cookbook.md`。

## 前置

- JMeter 5.6.x + JDK 17。`tools/*.sh` 通过 `JAVA_HOME` / `JMETER_HOME`(或 `JMETER_JAR`)/ `PY` / `ARTHAS_BOOT` 找到它们:
  复制 `tools/local.env.example` 为 `tools/local.env`(已 gitignore)填本机路径,或直接 export 同名环境变量
- 基础设施 + 服务已起(README §2、§3),`curl localhost:8080/actuator/health` 为 UP
- 在 `tests/perf/` 目录下执行,CSV 用相对路径

## 参数(全部 `-J` 传入,不改脚本)

### 公共

| 参数 | 默认 | 含义 |
|---|---|---|
| `host` | `localhost` | 服务地址 |
| `port` | `8080` | 服务端口 |
| `resultsFile` | `results/<脚本名>.jtl` | 原始结果文件(每个采样一行;`grab_race` 还保存响应体) |

### grab_race.jmx

| 参数 | 默认 | 含义 |
|---|---|---|
| `threads` | `20` | 同时抢单的线程数;**集合点的放行人数与它相同**,凑齐才一起发 |
| `rampup` | `0` | 线程启动时间(秒)。集合点会等所有线程到齐,所以 rampup 只影响建线程的节奏,不影响"同时发" |
| `groupId` | `1` | 目标工单所属组;`agents.csv` 里的坐席必须是这个组的(默认 3、4 都在 1 组) |
| `agentsCsv` | `agents.csv` | 坐席 id 池,线程轮询取 `X-User-Id` |

每次运行只针对**一张**工单。要多轮,重复运行(每次 setUp 都会新建一张),或用 `run_ladder.sh`。

### ticket_create.jmx

| 参数 | 默认 | 含义 |
|---|---|---|
| `threads` | `10` | 并发线程数 |
| `rampup` | `10` | 从 0 涨到 `threads` 用的秒数 |
| `duration` | `60` | 持续时长(秒),到时停 |
| `thinkMs` | `0` | 每次请求后的固定思考时间(毫秒) |
| `titlesCsv` | `titles.csv` | 标题 / 内容池,`|` 分隔。标题里可以放 `[SLOW]` `[ERROR]` 等挡板故障标记来压降级路径 |

### grab_throughput.jmx

| 参数 | 默认 | 含义 |
|---|---|---|
| `threads` / `rampup` / `duration` / `thinkMs` | 同 `ticket_create` | |
| `idsCsv` | `results/ticket_ids.csv` | 待抢工单 id 池,一行一个,表头 `ticketId`;不回收,取完线程停止 |
| `agentsCsv` | `agents.csv` | 坐席池(必须和 id 池里工单同组,否则 403) |

id 池用 `python tools/export_ids.py` 从库里导(只取 group 1 的 PENDING 单);多轮之间用 `python tools/reset_grabbed.py`
把上一轮抢走的重置回 PENDING 再重导。

### 一轮压测怎么跑(推荐:自动带环境状态)

```bash
bash tools/run_load.sh ticket_create.jmx 50 create_t50 60        # 脚本 线程 tag 持续秒
bash tools/run_load.sh grab_throughput.jmx 50 grab_t50 20
```
`run_load.sh` 会:压测前后各抓一份环境状态(`tools/env_state.py`:HikariCP 池大小、JVM 堆与 GC 累计、SLA 后台积压、
库内行数、MySQL 持久化 / 慢日志配置、LLM 熔断、MQ 队列)→ 每秒采 `/actuator/prometheus` → WSL 里采 `docker stats`
→ 跑 JMeter → 汇总成 `results/<tag>_report.md`,**报告头部就是两份环境状态**。
为什么强制:同一并发在不同时刻得到不同结果,原因是连接池的历史状态,见
`docs/findings/20260920-压测-同一并发不同成功数-连接池历史状态.md`。没有环境状态头的数字不可比较。

### 竞态复现一轮怎么跑

```bash
bash tools/grab_round.sh 20 r1          # grab_race 20 线程 → 自动查库取证(tools/grab_evidence.py)
python tools/grab_evidence.py --scan    # 全库扫:哪些工单 audit_log 里 to_status='ASSIGNED' 多于 1 条
```

### tools/ 一览

| 文件 | 干什么 |
|---|---|
| `run_load.sh` | 一轮压测的完整流程(见上) |
| `env_state.py` | 环境状态快照(markdown + json) |
| `metrics_sampler.py` | 每秒抓指标端点;`--summarize` 出峰值 / 均值 / 差分 |
| `docker_stats_loop.sh` | WSL 里循环 `docker stats`,容器 CPU |
| `jtl_stats.py` | jtl → QPS / P50 / P95 / P99 / 错误率,`--md` 出表 |
| `grab_round.sh` / `grab_evidence.py` | 竞态一轮 + 查库取证 |
| `race_timeline.py` | 从服务日志(MyBatis DEBUG)还原每个线程 SELECT / UPDATE 的毫秒时序 |
| `arthas.sh` / `parse_watch.py` | Arthas 批处理封装;把 `watch` 输出整理成按线程的 JDBC 时间线 |
| `mysql_probe.py` | 压测中每秒采 processlist 状态 + fsync / 文件等待差分 |
| `export_ids.py` / `reset_grabbed.py` | 抢单吞吐压测的数据准备 |
| `fault_probe.py` | 故障注入探针:health + 鉴权 + 创建 + 抢单 + 指标 + 库,一次一段追加到日志 |

### 梯度

`run_ladder.sh` 把同一脚本按并发梯度连跑几轮,每轮独立 jtl(不带环境状态,只是最简用法):

```bash
bash run_ladder.sh ticket_create.jmx "10 20 50" 60
bash run_ladder.sh grab_race.jmx "5 10 20 50"
```

## 怎么跑

```bash
cd tests/perf
jmeter -n -t grab_race.jmx -Jthreads=20 -JresultsFile=results/grab_20.jtl -l results/grab_20_summary.jtl
jmeter -n -t ticket_create.jmx -Jthreads=10 -Jrampup=10 -Jduration=60 -JresultsFile=results/create_10.jtl -l results/create_10_summary.jtl
jmeter -g results/create_10_summary.jtl -o results/create_10_html      # HTML 报告
```

Windows 下 `jmeter.bat` 同参数。GUI 模式只用来看和调脚本,压测一律 `-n`。

## 结果里看什么

采样标签在后处理器里被改写成带结果字段的形式,jtl / 聚合报告按标签分组就是一张分布表:

- `grab_race`:`grab | http=<状态> code=<业务码> agent=<发起坐席> assignee=<响应里的 assignee>`
  tearDown 那两个采样(终态、审计轨迹)的响应体也在 jtl 里(`responseData` 已开)。
  另外可以直接查库:`SELECT status, assignee_id FROM ticket WHERE id=?`、
  `SELECT from_status,to_status,operator_id FROM ticket_audit_log WHERE ticket_id=?`。
- `ticket_create`:`create | http=<状态> code=<业务码> category=<分类> priority=<优先级>`
  是否走了降级**接口看不出来**,压测前后各抓一次 `/actuator/prometheus` 里的
  `llm_fallback_total`、`llm_circuit_open_total`、`llm_call_duration_seconds` 分位数,
  或直接 `SELECT degraded, degrade_reason, COUNT(*) FROM llm_call_log GROUP BY 1,2`。

响应时间、吞吐、错误率看聚合报告或 HTML 报告。

## 清理

压测会造大量工单。清理用 SQL(五张表按 ticket_id 关联),或 `docker compose down -v` 重建:

```sql
DELETE FROM ticket_attachment WHERE ticket_id IN (SELECT id FROM ticket WHERE title LIKE '%perf%');
DELETE FROM ticket_audit_log  WHERE ticket_id IN (SELECT id FROM ticket WHERE title LIKE '%perf%');
DELETE FROM llm_call_log      WHERE ticket_id IN (SELECT id FROM ticket WHERE title LIKE '%perf%');
DELETE FROM mq_message_dedup  WHERE ticket_id IN (SELECT id FROM ticket WHERE title LIKE '%perf%');
DELETE FROM ticket WHERE title LIKE '%perf%';
```

`results/` 下的 `*.jtl`、`*.log`、HTML 目录已在 `.gitignore`,不要提交。

### 修复后回归(2026-09-21 新增)

```bash
bash tools/regress_grab.sh fix          # 2 线程 × 5 轮、20、100 线程,每轮取证 + 三层防线的指标差值,汇总 results/fix_regress_summary.md
bash tools/ladder_full.sh fix           # 清库 → 创建 10/20/50/100/200 × 60s → 抢单 10/20/50 × 20s、100/200 × 60s(与修复前同顺序)
bash tools/run_load.sh ticket_read.jmx 10 read_t10 20 "-JidsCsv=results/ticket_ids.csv"     # 读链路
python tools/to_platform.py fix_grab_t50 --post --baseline     # 一轮产物 → 质量数据平台(platform/README.md)
```

`grab_evidence.py` 现在有第四条结论:审计序列是否连续(第 k 行 to == 第 k+1 行 from,终态 == 最后一行 to)——KI-009 的反向断言。
`reset_grabbed.py` 重置时会补一条 `ASSIGNED→PENDING(perf reset)` 审计,否则工具自己会制造断裂。
结果与结论:`docs/findings/修复后回归验证.md`。
