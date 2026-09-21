# 压测轮次 fix_create_t50

脚本 `ticket_create.jmx`,线程 50,ramp-up 10s,持续 60s,额外参数 ``,执行时间 2026-09-21 01:50:40
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:49:21(fix_create_t50 之前) |
| 服务版本 | git 0b54afe,JVM uptime 433 s |
| HikariCP total/idle/active/pending(max) | 19/18/1/0 (20);acquire_max 0.0042345s,timeout_total 0 |
| JVM 堆已用 / 上限 | 56.3 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 27 次 / 0.141 s / 0.02 s |
| JVM 线程(live / blocked) | 109.0 / 0.0 |
| SLA 后台任务 | 扫描累计 14.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 12.4 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 24402 / 24402 / 24402 / 17622;按状态 PENDING=24402 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=20 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 24432.0 / 17611.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 8558} |
| HTTP 请求累计 | 24689.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:50:40(fix_create_t50 之后) |
| 服务版本 | git 0b54afe,JVM uptime 511 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 0.298247s,timeout_total 0 |
| JVM 堆已用 / 上限 | 205.9 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 45 次 / 0.175 s / 0.004 s |
| JVM 线程(live / blocked) | 148.0 / 0.0 |
| SLA 后台任务 | 扫描累计 16.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 11.1 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 45296 / 45296 / 45296 / 22496;按状态 PENDING=45296 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 45326.0 / 22486.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 24282} |
| HTTP 请求累计 | 45667.0 |

## JMeter 结果

```
fix_create_t50.jtl: samples=20894 wall=60.0s qps=348.1 avg=131.6 p50=127 p95=183 p99=226 max=417 errors=0 (0.00%) codes={'201': 20894}

fix_create_t50.jtl label 分布:
    6268  create | http=201 code=0 category=TECH priority=P0
    6268  create | http=201 code=0 category=OTHER priority=P2
    4179  create | http=201 code=0 category=BILLING priority=P1
    4179  create | http=201 code=0 category=REFUND priority=P1
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_create_t50_metrics.csv: 74 samples 01:49:22..01:50:40
  hikari_active    max=   20.00 avg=   14.20
  hikari_pending   max=   22.00 avg=    8.46
  jvm_threads      max=  149.00 avg=  140.65
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   48.00 avg=   34.16
  heap_used_mb     max=  660.32 avg=  323.62
  proc_cpu         max=    0.15 avg=    0.10
  sys_cpu          max=    0.73 avg=    0.52
  gc_count         delta=   18.00  (first=27.0 last=45.0)
  gc_sum_s         delta=    0.03  (first=0.141 last=0.175)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=20894.00  (first=24432.0 last=45326.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 4775.00  (first=17693.0 last=22468.0)
  http_count       delta=20975.00  (first=24691.0 last=45666.0)
  gc_max_s         max=0.020
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=75.4% max_cpu=99.8%
ticketqa-prometheus    samples=18 avg_cpu=0.1% max_cpu=0.6%
ticketqa-rabbitmq      samples=18 avg_cpu=19.3% max_cpu=9.4%
ticketqa-redis         samples=18 avg_cpu=2.6% max_cpu=5.5%
ticketqa-wiremock      samples=18 avg_cpu=59.5% max_cpu=99.7%
```
