# 压测轮次 fix_read_t100

脚本 `ticket_read.jmx`,线程 100,ramp-up 20s,持续 20s,额外参数 `-JidsCsv=results/ticket_ids.csv`,执行时间 2026-09-21 02:47:50
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 02:47:12(fix_read_t100 之前) |
| 服务版本 | git 0b54afe,JVM uptime 3903 s |
| HikariCP total/idle/active/pending(max) | 20/20/0/0 (20);acquire_max 0.455901s,timeout_total 0 |
| JVM 堆已用 / 上限 | 387.2 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 145 次 / 0.42 s / 0.005 s |
| JVM 线程(live / blocked) | 131.0 / 0.0 |
| SLA 后台任务 | 扫描累计 126.0 轮,升级累计 8700.0;库内待升级积压 18782 张,下一批到期 0.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 234370 / 87190 / 272338;按状态 ASSIGNED=24907,ESCALATED=8700,PENDING=53583 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 272368.0 / 272368.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 90726.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 02:47:50(fix_read_t100 之后) |
| 服务版本 | git 0b54afe,JVM uptime 3942 s |
| HikariCP total/idle/active/pending(max) | 20/20/0/0 (20);acquire_max 0.9232174s,timeout_total 0 |
| JVM 堆已用 / 上限 | 532.3 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 146 次 / 0.422 s / 0.003 s |
| JVM 线程(live / blocked) | 180.0 / 0.0 |
| SLA 后台任务 | 扫描累计 127.0 轮,升级累计 8800.0;库内待升级积压 20789 张,下一批到期 0.3 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 234470 / 87190 / 272538;按状态 ASSIGNED=24855,ESCALATED=8800,PENDING=53535 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 272568.0 / 272568.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 91881.0 |

## JMeter 结果

```
fix_read_t100.jtl: samples=3296 wall=20.7s qps=159.3 avg=317.8 p50=291 p95=799 p99=954 max=1423 errors=0 (0.00%) codes={'200': 3296}

fix_read_t100.jtl label 分布:
    1134  detail | GET /api/tickets/{id}
    1107  list | GET /api/tickets?status=&page=1&size=20
    1055  update | http=200
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_read_t100_metrics.csv: 36 samples 02:47:12..02:47:50
  hikari_active    max=   20.00 avg=    9.72
  hikari_pending   max=   81.00 avg=   17.64
  jvm_threads      max=  181.00 avg=  157.22
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   47.00 avg=   35.92
  heap_used_mb     max=  677.15 avg=  441.38
  proc_cpu         max=    0.04 avg=    0.02
  sys_cpu          max=    0.54 avg=    0.34
  gc_count         delta=    1.00  (first=145.0 last=146.0)
  gc_sum_s         delta=    0.00  (first=0.42 last=0.422)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=  200.00  (first=272368.0 last=272568.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta=  200.00  (first=272368.0 last=272568.0)
  http_count       delta= 1152.00  (first=90728.0 last=91880.0)
  gc_max_s         max=0.005
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=9 avg_cpu=191.8% max_cpu=384.3%
ticketqa-prometheus    samples=9 avg_cpu=0.1% max_cpu=0.5%
ticketqa-rabbitmq      samples=9 avg_cpu=0.4% max_cpu=0.8%
ticketqa-redis         samples=9 avg_cpu=1.0% max_cpu=3.3%
ticketqa-wiremock      samples=9 avg_cpu=0.9% max_cpu=2.5%
```
