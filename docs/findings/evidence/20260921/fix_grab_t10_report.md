# 压测轮次 fix_grab_t10

脚本 `grab_throughput.jmx`,线程 10,ramp-up 2s,持续 20s,额外参数 `-JidsCsv=results/ticket_ids.csv`,执行时间 2026-09-21 01:53:58
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:53:20(fix_grab_t10 之前) |
| 服务版本 | git 0b54afe,JVM uptime 672 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 2.6092919s,timeout_total 0 |
| JVM 堆已用 / 上限 | 388.7 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 78 次 / 0.262 s / 0.004 s |
| JVM 线程(live / blocked) | 299.0 / 0.0 |
| SLA 后台任务 | 扫描累计 22.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 8.5 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 87190 / 87190 / 31476;按状态 PENDING=87190 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 87220.0 / 31465.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 57225} |
| HTTP 请求累计 | 87751.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:53:58(fix_grab_t10 之后) |
| 服务版本 | git 0b54afe,JVM uptime 709 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 2.6092919s,timeout_total 0 |
| JVM 堆已用 / 上限 | 535.2 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 82 次 / 0.271 s / 0.004 s |
| JVM 线程(live / blocked) | 299.0 / 0.0 |
| SLA 后台任务 | 扫描累计 23.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 7.8 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 95071 / 87190 / 40383;按状态 ASSIGNED=7881,PENDING=79309 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 102982.0 / 40331.0 / 0.0;{'q.ticket.assigned': 4411, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 59860} |
| HTTP 请求累计 | 87824.0 |

## JMeter 结果

```
fix_grab_t10.jtl: samples=7881 wall=19.9s qps=395.7 avg=23.3 p50=23 p95=28 p99=32 max=48 errors=0 (0.00%) codes={'200': 7881}

fix_grab_t10.jtl label 分布:
    7881  grab | http=200 code=0 status=ASSIGNED
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_grab_t10_metrics.csv: 35 samples 01:53:21..01:53:58
  hikari_active    max=   12.00 avg=    5.89
  hikari_pending   max=    0.00 avg=    0.00
  jvm_threads      max=  300.00 avg=  299.60
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   38.00 avg=   31.17
  heap_used_mb     max=  641.70 avg=  366.51
  proc_cpu         max=    0.20 avg=    0.08
  sys_cpu          max=    0.77 avg=    0.47
  gc_count         delta=    4.00  (first=78.0 last=82.0)
  gc_sum_s         delta=    0.01  (first=0.262 last=0.271)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=15762.00  (first=87220.0 last=102982.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 8707.00  (first=31553.0 last=40260.0)
  http_count       delta=   70.00  (first=87753.0 last=87823.0)
  gc_max_s         max=0.004
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=8 avg_cpu=65.8% max_cpu=95.8%
ticketqa-prometheus    samples=8 avg_cpu=0.1% max_cpu=0.6%
ticketqa-rabbitmq      samples=8 avg_cpu=18.5% max_cpu=9.9%
ticketqa-redis         samples=8 avg_cpu=5.7% max_cpu=8.9%
ticketqa-wiremock      samples=8 avg_cpu=1.0% max_cpu=3.8%
```
