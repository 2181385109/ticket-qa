# 压测轮次 fix_read_t10

脚本 `ticket_read.jmx`,线程 10,ramp-up 2s,持续 20s,额外参数 `-JidsCsv=results/ticket_ids.csv`,执行时间 2026-09-21 02:46:32
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 02:45:55(fix_read_t10 之前) |
| 服务版本 | git 0b54afe,JVM uptime 3826 s |
| HikariCP total/idle/active/pending(max) | 3/3/0/0 (20);acquire_max 0.0060865s,timeout_total 0 |
| JVM 堆已用 / 上限 | 143.3 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 143 次 / 0.414 s / 0.005 s |
| JVM 线程(live / blocked) | 82.0 / 0.0 |
| SLA 后台任务 | 扫描累计 124.0 轮,升级累计 8500.0;库内待升级积压 17654 张,下一批到期 0.9 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 234170 / 87190 / 271938;按状态 ASSIGNED=24999,ESCALATED=8500,PENDING=53691 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=4 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 271968.0 / 271968.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 88422.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 02:46:32(fix_read_t10 之后) |
| 服务版本 | git 0b54afe,JVM uptime 3864 s |
| HikariCP total/idle/active/pending(max) | 20/20/0/0 (20);acquire_max 0.1171031s,timeout_total 0 |
| JVM 堆已用 / 上限 | 268.6 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 144 次 / 0.417 s / 0.005 s |
| JVM 线程(live / blocked) | 115.0 / 0.0 |
| SLA 后台任务 | 扫描累计 125.0 轮,升级累计 8600.0;库内待升级积压 17554 张,下一批到期 0.3 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 234270 / 87190 / 272138;按状态 ASSIGNED=24954,ESCALATED=8600,PENDING=53636 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 272168.0 / 272168.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 89594.0 |

## JMeter 结果

```
fix_read_t10.jtl: samples=3149 wall=20.0s qps=157.4 avg=60.0 p50=16 p95=211 p99=266 max=363 errors=0 (0.00%) codes={'200': 3149}

fix_read_t10.jtl label 分布:
    1053  detail | GET /api/tickets/{id}
    1053  list | GET /api/tickets?status=&page=1&size=20
    1043  update | http=200
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_read_t10_metrics.csv: 35 samples 02:45:55..02:46:32
  hikari_active    max=   17.00 avg=    5.11
  hikari_pending   max=    7.00 avg=    0.23
  jvm_threads      max=  116.00 avg=  106.34
  threads_blocked  max=    1.00 avg=    0.03
  threads_runnable max=   43.00 avg=   31.23
  heap_used_mb     max=  670.34 avg=  295.19
  proc_cpu         max=    0.20 avg=    0.03
  sys_cpu          max=    0.71 avg=    0.35
  gc_count         delta=    1.00  (first=143.0 last=144.0)
  gc_sum_s         delta=    0.00  (first=0.414 last=0.417)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=  200.00  (first=271968.0 last=272168.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta=  200.00  (first=271968.0 last=272168.0)
  http_count       delta= 1170.00  (first=88423.0 last=89593.0)
  gc_max_s         max=0.005
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=8 avg_cpu=219.0% max_cpu=379.8%
ticketqa-prometheus    samples=8 avg_cpu=0.0% max_cpu=0.1%
ticketqa-rabbitmq      samples=8 avg_cpu=4.8% max_cpu=35.8%
ticketqa-redis         samples=8 avg_cpu=1.4% max_cpu=3.6%
ticketqa-wiremock      samples=8 avg_cpu=1.1% max_cpu=3.1%
```
