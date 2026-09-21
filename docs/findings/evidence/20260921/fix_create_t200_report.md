# 压测轮次 fix_create_t200

脚本 `ticket_create.jmx`,线程 200,ramp-up 40s,持续 60s,额外参数 ``,执行时间 2026-09-21 01:53:19
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:52:00(fix_create_t200 之前) |
| 服务版本 | git 0b54afe,JVM uptime 592 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 1.1624736s,timeout_total 0 |
| JVM 堆已用 / 上限 | 170.2 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 62 次 / 0.213 s / 0.004 s |
| JVM 线程(live / blocked) | 199.0 / 0.0 |
| SLA 后台任务 | 扫描累计 19.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 9.8 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 66189 / 66189 / 66189 / 27083;按状态 PENDING=66189 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 66219.0 / 27075.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 40662} |
| HTTP 请求累计 | 66651.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:53:18(fix_create_t200 之后) |
| 服务版本 | git 0b54afe,JVM uptime 670 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 2.6092919s,timeout_total 0 |
| JVM 堆已用 / 上限 | 355.7 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 78 次 / 0.262 s / 0.004 s |
| JVM 线程(live / blocked) | 299.0 / 0.0 |
| SLA 后台任务 | 扫描累计 22.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 8.5 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 87190 / 87190 / 31164;按状态 PENDING=87190 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 87220.0 / 31156.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 57225} |
| HTTP 请求累计 | 87748.0 |

## JMeter 结果

```
fix_create_t200.jtl: samples=21001 wall=60.4s qps=347.9 avg=384.2 p50=315 p95=966 p99=1423 max=2997 errors=0 (0.00%) codes={'201': 21001}

fix_create_t200.jtl label 分布:
    6302  create | http=201 code=0 category=OTHER priority=P2
    6299  create | http=201 code=0 category=TECH priority=P0
    4201  create | http=201 code=0 category=REFUND priority=P1
    4199  create | http=201 code=0 category=BILLING priority=P1
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_create_t200_metrics.csv: 73 samples 01:52:01..01:53:18
  hikari_active    max=   20.00 avg=   14.32
  hikari_pending   max=  174.00 avg=   74.21
  jvm_threads      max=  300.00 avg=  253.25
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   47.00 avg=   34.29
  heap_used_mb     max=  654.67 avg=  338.71
  proc_cpu         max=    0.17 avg=    0.10
  sys_cpu          max=    0.72 avg=    0.53
  gc_count         delta=   16.00  (first=62.0 last=78.0)
  gc_sum_s         delta=    0.05  (first=0.213 last=0.262)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=21001.00  (first=66219.0 last=87220.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 4017.00  (first=27159.0 last=31176.0)
  http_count       delta=21097.00  (first=66652.0 last=87749.0)
  gc_max_s         max=0.004
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=73.6% max_cpu=99.9%
ticketqa-prometheus    samples=18 avg_cpu=0.1% max_cpu=1.1%
ticketqa-rabbitmq      samples=18 avg_cpu=14.5% max_cpu=62.7%
ticketqa-redis         samples=18 avg_cpu=2.6% max_cpu=5.3%
ticketqa-wiremock      samples=18 avg_cpu=61.4% max_cpu=98.0%
```
