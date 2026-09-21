# 压测轮次 create_t20

脚本 `ticket_create.jmx`,线程 20,ramp-up 4s,持续 60s,额外参数 ``,执行时间 2026-09-20 19:07:59
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:06:41(create_t20 之前) |
| 服务版本 | git 92ac612,JVM uptime 4335 s |
| HikariCP total/idle/active/pending(max) | 10/10/0/0 (20);acquire_max 0.0147544s,timeout_total 0 |
| JVM 堆已用 / 上限 | 205.2 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 27 次 / 0.243 s / 0.005 s |
| JVM 线程(live / blocked) | 110.0 / 0.0 |
| SLA 后台任务 | 扫描累计 143.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 13.5 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 9043 / 9043 / 9043 / 9043;按状态 PENDING=9043 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=11 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 23461.0 / 23461.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 17959.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:07:59(create_t20 之后) |
| 服务版本 | git 92ac612,JVM uptime 4412 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 0.0189456s,timeout_total 0 |
| JVM 堆已用 / 上限 | 426.0 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 43 次 / 0.274 s / 0.005 s |
| JVM 线程(live / blocked) | 122.0 / 0.0 |
| SLA 后台任务 | 扫描累计 145.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 12.3 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 25321 / 25321 / 25321 / 18420;按状态 PENDING=25321 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 39739.0 / 32800.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 8540} |
| HTTP 请求累计 | 34319.0 |

## JMeter 结果

```
create_t20.jtl: samples=16278 wall=60.0s qps=271.4 avg=71.0 p50=70 p95=81 p99=88 max=142 errors=0 (0.00%) codes={'201': 16278}

create_t20.jtl label 分布:
    4884  create | http=201 code=0 category=TECH priority=P0
    4882  create | http=201 code=0 category=OTHER priority=P2
    3256  create | http=201 code=0 category=BILLING priority=P1
    3256  create | http=201 code=0 category=REFUND priority=P1
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/create_t20_metrics.csv: 73 samples 19:06:42..19:07:58
  hikari_active    max=   15.00 avg=    6.04
  hikari_pending   max=    0.00 avg=    0.00
  jvm_threads      max=  123.00 avg=  120.04
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   60.00 avg=   55.49
  heap_used_mb     max=  663.92 avg=  351.66
  proc_cpu         max=    0.13 avg=    0.07
  sys_cpu          max=    0.58 avg=    0.43
  gc_count         delta=   16.00  (first=27.0 last=43.0)
  gc_sum_s         delta=    0.03  (first=0.243 last=0.274)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=16278.00  (first=23461.0 last=39739.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 9287.00  (first=23461.0 last=32748.0)
  http_count       delta=16358.00  (first=17960.0 last=34318.0)
  gc_max_s         max=0.005
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=64.2% max_cpu=81.9%
ticketqa-prometheus    samples=18 avg_cpu=0.0% max_cpu=0.6%
ticketqa-rabbitmq      samples=18 avg_cpu=14.4% max_cpu=90.0%
ticketqa-redis         samples=18 avg_cpu=2.2% max_cpu=5.1%
ticketqa-wiremock      samples=18 avg_cpu=24.8% max_cpu=53.5%
```
