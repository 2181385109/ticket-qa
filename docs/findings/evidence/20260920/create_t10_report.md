# 压测轮次 create_t10

脚本 `ticket_create.jmx`,线程 10,ramp-up 2s,持续 60s,额外参数 ``,执行时间 2026-09-20 19:06:28
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:05:11(create_t10 之前) |
| 服务版本 | git 92ac612,JVM uptime 4244 s |
| HikariCP total/idle/active/pending(max) | 3/3/0/0 (20);acquire_max 0.0004036s,timeout_total 0 |
| JVM 堆已用 / 上限 | 173.9 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 17 次 / 0.21 s / 0.02 s |
| JVM 线程(live / blocked) | 96.0 / 0.0 |
| SLA 后台任务 | 扫描累计 140.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 None 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 0 / 0 / 0 / 0;按状态 None |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=4 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 14418.0 / 14418.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 8832.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:06:28(create_t10 之后) |
| 服务版本 | git 92ac612,JVM uptime 4321 s |
| HikariCP total/idle/active/pending(max) | 10/10/0/0 (20);acquire_max 0.0147544s,timeout_total 0 |
| JVM 堆已用 / 上限 | 200.2 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 27 次 / 0.243 s / 0.005 s |
| JVM 线程(live / blocked) | 110.0 / 0.0 |
| SLA 后台任务 | 扫描累计 142.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 13.8 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 9043 / 9043 / 9043 / 9043;按状态 PENDING=9043 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=11 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 23461.0 / 23461.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 17957.0 |

## JMeter 结果

```
create_t10.jtl: samples=9043 wall=60.0s qps=150.8 avg=64.8 p50=64 p95=72 p99=77 max=144 errors=0 (0.00%) codes={'201': 9043}

create_t10.jtl label 分布:
    2713  create | http=201 code=0 category=TECH priority=P0
    2712  create | http=201 code=0 category=OTHER priority=P2
    1809  create | http=201 code=0 category=BILLING priority=P1
    1809  create | http=201 code=0 category=REFUND priority=P1
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/create_t10_metrics.csv: 73 samples 19:05:11..19:06:28
  hikari_active    max=    8.00 avg=    3.26
  hikari_pending   max=    0.00 avg=    0.00
  jvm_threads      max=  111.00 avg=  107.86
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   59.00 avg=   52.85
  heap_used_mb     max=  652.01 avg=  318.52
  proc_cpu         max=    0.34 avg=    0.07
  sys_cpu          max=    0.75 avg=    0.35
  gc_count         delta=   10.00  (first=17.0 last=27.0)
  gc_sum_s         delta=    0.03  (first=0.21 last=0.243)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta= 9043.00  (first=14418.0 last=23461.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 9043.00  (first=14418.0 last=23461.0)
  http_count       delta= 9123.00  (first=8833.0 last=17956.0)
  gc_max_s         max=0.020
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=44.2% max_cpu=59.3%
ticketqa-prometheus    samples=18 avg_cpu=0.1% max_cpu=0.7%
ticketqa-rabbitmq      samples=18 avg_cpu=11.6% max_cpu=81.7%
ticketqa-redis         samples=18 avg_cpu=1.7% max_cpu=3.9%
ticketqa-wiremock      samples=18 avg_cpu=14.9% max_cpu=9.8%
```
