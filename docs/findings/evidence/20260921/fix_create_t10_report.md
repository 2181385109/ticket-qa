# 压测轮次 fix_create_t10

脚本 `ticket_create.jmx`,线程 10,ramp-up 2s,持续 60s,额外参数 ``,执行时间 2026-09-21 01:48:02
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:46:44(fix_create_t10 之前) |
| 服务版本 | git 0b54afe,JVM uptime 276 s |
| HikariCP total/idle/active/pending(max) | 11/11/0/0 (20);acquire_max 0.1050617s,timeout_total 0 |
| JVM 堆已用 / 上限 | 104.4 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 1 次 / 0.022 s / 0.022 s |
| JVM 线程(live / blocked) | 83.0 / 0.0 |
| SLA 后台任务 | 扫描累计 8.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 None 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 0 / 0 / 0 / 0;按状态 None |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=12 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 30.0 / 30.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 122.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:48:01(fix_create_t10 之后) |
| 服务版本 | git 0b54afe,JVM uptime 353 s |
| HikariCP total/idle/active/pending(max) | 11/11/0/0 (20);acquire_max 0.1050617s,timeout_total 0 |
| JVM 堆已用 / 上限 | 618.6 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 10 次 / 0.085 s / 0.022 s |
| JVM 线程(live / blocked) | 100.0 / 0.0 |
| SLA 后台任务 | 扫描累计 11.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 13.8 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 8586 / 8586 / 8586 / 8586;按状态 PENDING=8586 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=12 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 8616.0 / 8616.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 8789.0 |

## JMeter 结果

```
fix_create_t10.jtl: samples=8586 wall=60.0s qps=143.2 avg=68.2 p50=67 p95=78 p99=87 max=168 errors=0 (0.00%) codes={'201': 8586}

fix_create_t10.jtl label 分布:
    2576  create | http=201 code=0 category=TECH priority=P0
    2575  create | http=201 code=0 category=OTHER priority=P2
    1718  create | http=201 code=0 category=BILLING priority=P1
    1717  create | http=201 code=0 category=REFUND priority=P1
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_create_t10_metrics.csv: 72 samples 01:46:45..01:48:01
  hikari_active    max=   10.00 avg=    3.38
  hikari_pending   max=    0.00 avg=    0.00
  jvm_threads      max=  100.00 avg=   96.75
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   34.00 avg=   29.40
  heap_used_mb     max=  618.24 avg=  362.65
  proc_cpu         max=    0.27 avg=    0.10
  sys_cpu          max=    0.69 avg=    0.43
  gc_count         delta=    9.00  (first=1.0 last=10.0)
  gc_sum_s         delta=    0.06  (first=0.022 last=0.085)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta= 8586.00  (first=30.0 last=8616.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 8586.00  (first=30.0 last=8616.0)
  http_count       delta= 8665.00  (first=123.0 last=8788.0)
  gc_max_s         max=0.022
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=49.2% max_cpu=70.2%
ticketqa-prometheus    samples=18 avg_cpu=0.0% max_cpu=0.6%
ticketqa-rabbitmq      samples=18 avg_cpu=13.9% max_cpu=8.0%
ticketqa-redis         samples=18 avg_cpu=1.6% max_cpu=4.1%
ticketqa-wiremock      samples=18 avg_cpu=45.4% max_cpu=71.5%
```
