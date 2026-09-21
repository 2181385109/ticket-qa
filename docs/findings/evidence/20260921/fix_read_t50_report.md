# 压测轮次 fix_read_t50

脚本 `ticket_read.jmx`,线程 50,ramp-up 10s,持续 20s,额外参数 `-JidsCsv=results/ticket_ids.csv`,执行时间 2026-09-21 02:47:11
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 02:46:33(fix_read_t50 之前) |
| 服务版本 | git 0b54afe,JVM uptime 3865 s |
| HikariCP total/idle/active/pending(max) | 20/20/0/0 (20);acquire_max 0.1171031s,timeout_total 0 |
| JVM 堆已用 / 上限 | 270.6 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 144 次 / 0.417 s / 0.005 s |
| JVM 线程(live / blocked) | 115.0 / 0.0 |
| SLA 后台任务 | 扫描累计 125.0 轮,升级累计 8600.0;库内待升级积压 17554 张,下一批到期 0.2 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 234270 / 87190 / 272138;按状态 ASSIGNED=24954,ESCALATED=8600,PENDING=53636 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 272168.0 / 272168.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 89595.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 02:47:11(fix_read_t50 之后) |
| 服务版本 | git 0b54afe,JVM uptime 3902 s |
| HikariCP total/idle/active/pending(max) | 20/20/0/0 (20);acquire_max 0.455901s,timeout_total 0 |
| JVM 堆已用 / 上限 | 382.2 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 145 次 / 0.42 s / 0.005 s |
| JVM 线程(live / blocked) | 131.0 / 0.0 |
| SLA 后台任务 | 扫描累计 126.0 轮,升级累计 8700.0;库内待升级积压 18718 张,下一批到期 0.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 234370 / 87190 / 272338;按状态 ASSIGNED=24907,ESCALATED=8700,PENDING=53583 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 272368.0 / 272368.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 90724.0 |

## JMeter 结果

```
fix_read_t50.jtl: samples=3250 wall=20.2s qps=160.6 avg=233.6 p50=195 p95=616 p99=735 max=940 errors=0 (0.00%) codes={'200': 3250}

fix_read_t50.jtl label 分布:
    1100  detail | GET /api/tickets/{id}
    1089  list | GET /api/tickets?status=&page=1&size=20
    1061  update | http=200
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_read_t50_metrics.csv: 36 samples 02:46:34..02:47:11
  hikari_active    max=   20.00 avg=    9.42
  hikari_pending   max=   33.00 avg=   11.06
  jvm_threads      max=  132.00 avg=  126.67
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   47.00 avg=   35.47
  heap_used_mb     max=  655.62 avg=  358.40
  proc_cpu         max=    0.05 avg=    0.02
  sys_cpu          max=    0.53 avg=    0.34
  gc_count         delta=    1.00  (first=144.0 last=145.0)
  gc_sum_s         delta=    0.00  (first=0.417 last=0.42)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=  200.00  (first=272168.0 last=272368.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta=  200.00  (first=272168.0 last=272368.0)
  http_count       delta= 1129.00  (first=89596.0 last=90725.0)
  gc_max_s         max=0.005
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=9 avg_cpu=210.0% max_cpu=381.0%
ticketqa-prometheus    samples=9 avg_cpu=0.0% max_cpu=0.1%
ticketqa-rabbitmq      samples=9 avg_cpu=12.8% max_cpu=58.7%
ticketqa-redis         samples=9 avg_cpu=1.2% max_cpu=2.2%
ticketqa-wiremock      samples=9 avg_cpu=0.3% max_cpu=2.2%
```
