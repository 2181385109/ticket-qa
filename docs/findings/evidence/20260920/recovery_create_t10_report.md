# 压测轮次 recovery_create_t10

脚本 `ticket_create.jmx`,线程 10,ramp-up 2s,持续 30s,额外参数 ``,执行时间 2026-09-20 21:55:19
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 21:54:32(recovery_create_t10 之前) |
| 服务版本 | git 92ac612,JVM uptime 14405 s |
| HikariCP total/idle/active/pending(max) | 6/6/0/0 (20);acquire_max 0.0006787s,timeout_total 0 |
| JVM 堆已用 / 上限 | 196.3 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 282 次 / 0.854 s / 0.012 s |
| JVM 线程(live / blocked) | 131.0 / 0.0 |
| SLA 后台任务 | 扫描累计 467.0 轮,升级累计 30475.0;库内待升级积压 0 张,下一批到期 14.7 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 102 / 129 / 102 / 4264;按状态 ASSIGNED=27,PENDING=75 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=7 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=8 open=1 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 581800.0 / 581800.0 / 9.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 102118.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 21:55:19(recovery_create_t10 之后) |
| 服务版本 | git 92ac612,JVM uptime 14453 s |
| HikariCP total/idle/active/pending(max) | 11/11/0/0 (20);acquire_max 0.0074243s,timeout_total 0 |
| JVM 堆已用 / 上限 | 676.7 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 286 次 / 0.865 s / 0.012 s |
| JVM 线程(live / blocked) | 137.0 / 0.0 |
| SLA 后台任务 | 扫描累计 468.0 轮,升级累计 30475.0;库内待升级积压 0 张,下一批到期 13.9 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 4332 / 4359 / 4332 / 8494;按状态 ASSIGNED=27,PENDING=4305 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=12 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=8 open=1 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 586030.0 / 586030.0 / 9.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 106399.0 |

## JMeter 结果

```
recovery_create_t10.jtl: samples=4230 wall=30.0s qps=141.2 avg=68.0 p50=67 p95=78 p99=86 max=112 errors=0 (0.00%) codes={'201': 4230}

recovery_create_t10.jtl label 分布:
    1269  create | http=201 code=0 category=TECH priority=P0
    1269  create | http=201 code=0 category=OTHER priority=P2
     846  create | http=201 code=0 category=REFUND priority=P1
     846  create | http=201 code=0 category=BILLING priority=P1
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/recovery_create_t10_metrics.csv: 45 samples 21:54:32..21:55:19
  hikari_active    max=    7.00 avg=    2.40
  hikari_pending   max=    0.00 avg=    0.00
  jvm_threads      max=  139.00 avg=  136.82
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   71.00 avg=   66.49
  heap_used_mb     max=  673.70 avg=  435.80
  proc_cpu         max=    0.10 avg=    0.04
  sys_cpu          max=    0.70 avg=    0.42
  gc_count         delta=    4.00  (first=282.0 last=286.0)
  gc_sum_s         delta=    0.01  (first=0.854 last=0.865)
  llm_fallback     delta=    0.00  (first=8.0 last=8.0)
  llm_circuit_open delta=    0.00  (first=1.0 last=1.0)
  mq_published     delta= 4230.00  (first=581800.0 last=586030.0)
  mq_publish_failed delta=    0.00  (first=9.0 last=9.0)
  mq_consumed      delta= 4230.00  (first=581800.0 last=586030.0)
  http_count       delta= 4279.00  (first=102119.0 last=106398.0)
  gc_max_s         max=0.012
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=10 avg_cpu=46.6% max_cpu=67.1%
ticketqa-prometheus    samples=10 avg_cpu=0.0% max_cpu=0.1%
ticketqa-rabbitmq      samples=10 avg_cpu=15.3% max_cpu=90.3%
ticketqa-redis         samples=10 avg_cpu=1.8% max_cpu=4.1%
ticketqa-wiremock      samples=10 avg_cpu=41.7% max_cpu=77.6%
```
