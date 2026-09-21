# platform — 极简质量数据平台

只做三件事(ADR-022),其余一概不做(没有用例管理 / 任务调度 / 权限 / 用户):

1. **执行记录入库**:批次、用例数、通过率、耗时、覆盖率
2. **趋势**:通过率和覆盖率随批次的折线
3. **性能基线对比**:本轮压测 vs 基线,QPS 下降 ≥ 10% 或 P99 上升 ≥ 20% 标红;
   **基线连同压测前的环境状态一起存**(池、堆、GC、后台任务、数据量、MQ 积压、MySQL 配置),
   环境显著不同时结论降级为「不可信」——按 KI-010,不带环境的对比是在比环境不是比代码

后端 Spring Boot 3 + MyBatis-Plus(端口 8081,复用被测服务的 MySQL,表 `qa_test_run` / `qa_perf_run` 启动时幂等建出);
前端一张静态页,Vue 3 + Chart.js 走 CDN,没有 node_modules、没有构建。

## 起

```bash
cd platform
mvn -B -DskipTests package
java -jar target/ticket-qa-platform-0.1.0.jar        # http://localhost:8081
# 环境变量与被测服务同名:MYSQL_HOST/PORT/DATABASE/USER/PASSWORD,PLATFORM_PORT
```

`mvn test` 跑 `PerfComparatorTest`(对比判定表,7 条)。

## 导入接口

响应都是 `{"code","message","data"}`,`code=0` 成功;唯一键重复 = **覆盖**(CI 重跑同一批次是常态),不是 409。

### 1. 执行记录 `POST /api/runs`

```json
{
  "batchNo": "local-20260921031447",   // 必填,唯一;CI 用 GITHUB_RUN_ID
  "suite": "api",                      // 必填:unit / api / security / all
  "source": "local",                   // ci / local,默认 local
  "commitSha": "0b54afe…", "branch": "main",
  "startedAt": "2026-09-21 03:14:47",  // 必填,yyyy-MM-dd HH:mm:ss
  "durationMs": 412110,
  "total": 312, "passed": 308, "failed": 0, "skipped": 1, "xfailed": 3,   // total / passed 必填
  "lineCoverage": 93.51, "branchCoverage": 90.04, "coverageSource": "jacoco",   // 可空
  "note": "任意备注"
}
```

`passRate` 不让传,平台按 `passed / (total − skipped − xfailed) × 100` 算——skipped 和 xfailed 既不是通过也不是失败,
算进分母会让全绿批次显示 98%。

从标准产物生成并 POST(`tests/tools/publish_run.py`):

```bash
cd tests
python -m pytest --junitxml=junit.xml                     # 或 CI 里已有的 coverage run …
python tools/publish_run.py --suite api --junit junit.xml --coverage-xml coverage.xml --post
python tools/publish_run.py --suite unit --junit "../service/target/surefire-reports/TEST-*.xml" \
       --jacoco ../service/target/site/jacoco/jacoco.xml --post
```

查询:`GET /api/runs?suite=&limit=`、`GET /api/runs/{id}`、`GET /api/runs/trend?suite=&limit=`(按时间升序的趋势点)。

### 2. 压测轮次 `POST /api/perf-runs`

```json
{
  "tag": "fix_grab_t50",              // 必填,唯一,与 tests/perf/results/<tag> 对应
  "scenario": "grab",                 // 必填:create / grab / read / grab_race …
  "threads": 50,                      // 必填
  "durationS": 20, "samples": 8991,   // samples 必填
  "qps": 449.89, "avgMs": 83.38, "p50Ms": 96, "p95Ms": 111, "p99Ms": 121, "maxMs": 184,   // qps / p99Ms 必填
  "errorRate": 0.0,                   // %
  "commitSha": "0b54afe", "executedAt": "2026-09-21 01:55:18",   // executedAt 必填
  "env": { "...": "tests/perf/tools/env_state.py --json 的整份输出" },   // 必填且非空,没有环境状态的轮次拒收
  "baseline": true,                   // 可选:同时设为该 scenario+threads 的基线(旧基线自动让位)
  "note": "2026-09-21 修复后梯度"
}
```

`env` 的结构由 `env_state.py` 决定;对比时会读这些键:`hikari.total/max`、`jvm.heap_max_mb`、`mysql.ticket_rows`、
`mysql.sla_backlog`、`mysql.mysql_vars.{innodb_flush_log_at_trx_commit,sync_binlog,transaction_isolation,innodb_buffer_pool_size,max_connections,slow_query_log}`、
`mq.queues.*`(求和)、`llm.circuit_state`、`git`。缺哪个键就跳过哪个,不报错。

从 `run_load.sh` 的产物直接生成并 POST(`tests/perf/tools/to_platform.py`):

```bash
cd tests/perf
python tools/to_platform.py fix_grab_t50                    # 只打印 JSON
python tools/to_platform.py fix_grab_t50 --post --baseline  # 导入并设为 grab/50 的基线
python tools/to_platform.py grab_t50 --post                 # 导入修复前那轮(同 scenario/threads)
```

它读 `results/<tag>.jtl`(汇总,算法同 `jtl_stats.py`)、`results/<tag>_env_before.json`(环境)、
`results/<tag>_report.md`(线程 / 时长 / 执行时间);scenario / threads 从 tag 的 `<x>_<scenario>_t<N>` 猜,猜不出用 `--scenario` / `--threads`。

查询与对比:

| 接口 | 说明 |
|---|---|
| `GET /api/perf-runs?scenario=&threads=&limit=` | 列表,新的在前 |
| `PUT /api/perf-runs/{id}/baseline` | 设为该 scenario+threads 的基线 |
| `GET /api/perf-runs/{id}/compare?baselineId=` | 本轮 vs 基线;不给 baselineId 就用当前基线,没有基线 → 404(不会偷偷拿上一轮来比) |

对比返回:`qpsDeltaPct / p50 / p95 / p99DeltaPct`(`(本轮 − 基线) / 基线 × 100`)、`qpsRed / p99Red`、
`verdict`(`GREEN` / `RED` / `UNRELIABLE`)、`comparable`、`envDiffs[]`(每项 `key / baseline / current / significant / why`)。
阈值在 `application.yml` 的 `platform.compare.*`。

## 2026-09-21 导入的真实数据

修复后梯度 7 轮(`fix_*`,设为基线)+ 修复前 6 轮(`create_t*` / `grab_t*`)。六组"修复前 vs 修复后"对比**全部判为 UNRELIABLE**:
起跑池 3 vs 11、后台 SLA 积压 0 vs 3907~25590、MQ 积压相差数万——平台把 findings 里"这 4% 差异不能坐实为修复代价"的判断
变成了机器可复现的结论。要拿到可信的 A/B,得在同一环境状态下各跑三轮。
