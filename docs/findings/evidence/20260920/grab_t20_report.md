# 压测轮次 grab_t20

脚本 `grab_throughput.jmx`,线程 20,ramp-up 4s,持续 20s,额外参数 ``,执行时间 2026-09-20 19:23:25
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:22:47(grab_t20 之前) |
| 服务版本 | git 92ac612,JVM uptime 5301 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.0098935s,timeout_total 0 |
| JVM 堆已用 / 上限 | 540.0 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 135 次 / 0.479 s / 0.002 s |
| JVM 线程(live / blocked) | 108.0 / 0.0 |
| SLA 后台任务 | 扫描累计 175.0 轮,升级累计 3375.0;库内待升级积压 7097 张,下一批到期 0.4 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 131257 / 90629 / 165057;按状态 ESCALATED=500,PENDING=90127 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 186305.0 / 179391.0 / 0.0;{'q.ticket.assigned': 4088, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 4201} |
| HTTP 请求累计 | 100286.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:23:25(grab_t20 之后) |
| 服务版本 | git 92ac612,JVM uptime 5338 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.0564941s,timeout_total 0 |
| JVM 堆已用 / 上限 | 487.1 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 140 次 / 0.489 s / 0.002 s |
| JVM 线程(live / blocked) | 108.0 / 0.0 |
| SLA 后台任务 | 扫描累计 176.0 轮,升级累计 3475.0;库内待升级积压 8568 张,下一批到期 0.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 140357 / 90629 / 173702;按状态 ASSIGNED=8955,ESCALATED=600,PENDING=81072 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 204505.0 / 188032.0 / 0.0;{'q.ticket.assigned': 9354, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 9675} |
| HTTP 请求累计 | 100326.0 |

## JMeter 结果

```
grab_t20.jtl: samples=9000 wall=19.9s qps=452.0 avg=39.4 p50=41 p95=47 p99=50 max=97 errors=0 (0.00%) codes={'200': 9000}

grab_t20.jtl label 分布:
    9000  grab | http=200 code=0 status=ASSIGNED
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/grab_t20_metrics.csv: 36 samples 19:22:48..19:23:25
  hikari_active    max=   20.00 avg=   10.42
  hikari_pending   max=    2.00 avg=    0.72
  jvm_threads      max=  109.00 avg=  108.61
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   63.00 avg=   54.31
  heap_used_mb     max=  674.71 avg=  378.29
  proc_cpu         max=    0.12 avg=    0.07
  sys_cpu          max=    0.63 avg=    0.43
  gc_count         delta=    5.00  (first=135.0 last=140.0)
  gc_sum_s         delta=    0.01  (first=0.479 last=0.489)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=18200.00  (first=186305.0 last=204505.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 8532.00  (first=179582.0 last=188114.0)
  http_count       delta=   40.00  (first=100287.0 last=100327.0)
  gc_max_s         max=0.002
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=9 avg_cpu=65.1% max_cpu=93.1%
ticketqa-prometheus    samples=9 avg_cpu=0.2% max_cpu=0.9%
ticketqa-rabbitmq      samples=9 avg_cpu=20.6% max_cpu=61.1%
ticketqa-redis         samples=9 avg_cpu=2.6% max_cpu=3.7%
ticketqa-wiremock      samples=9 avg_cpu=0.9% max_cpu=2.9%
```
