# 压测轮次 fix_grab_t50

脚本 `grab_throughput.jmx`,线程 50,ramp-up 10s,持续 20s,额外参数 `-JidsCsv=results/ticket_ids.csv`,执行时间 2026-09-21 01:55:18
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:54:40(fix_grab_t50 之前) |
| 服务版本 | git 0b54afe,JVM uptime 751 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 2.6092919s,timeout_total 0 |
| JVM 堆已用 / 上限 | 176.3 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 87 次 / 0.281 s / 0.004 s |
| JVM 线程(live / blocked) | 278.0 / 0.0 |
| SLA 后台任务 | 扫描累计 24.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 7.1 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 119916 / 87190 / 50179;按状态 PENDING=87190 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 119946.0 / 50133.0 / 0.0;{'q.ticket.assigned': 8283, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 63732} |
| HTTP 请求累计 | 87868.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:55:17(fix_grab_t50 之后) |
| 服务版本 | git 0b54afe,JVM uptime 789 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.1356211s,timeout_total 0 |
| JVM 堆已用 / 上限 | 296.1 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 91 次 / 0.29 s / 0.004 s |
| JVM 线程(live / blocked) | 277.0 / 0.0 |
| SLA 后台任务 | 扫描累计 26.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 6.5 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 128907 / 87190 / 57494;按状态 ASSIGNED=8991,PENDING=78199 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 137928.0 / 57449.0 / 0.0;{'q.ticket.assigned': 13230, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 68680} |
| HTTP 请求累计 | 87908.0 |

## JMeter 结果

```
fix_grab_t50.jtl: samples=8991 wall=20.0s qps=449.9 avg=83.4 p50=96 p95=111 p99=121 max=184 errors=0 (0.00%) codes={'200': 8991}

fix_grab_t50.jtl label 分布:
    8991  grab | http=200 code=0 status=ASSIGNED
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_grab_t50_metrics.csv: 36 samples 01:54:40..01:55:18
  hikari_active    max=   20.00 avg=   10.19
  hikari_pending   max=   32.00 avg=   10.50
  jvm_threads      max=  279.00 avg=  278.25
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   37.00 avg=   30.39
  heap_used_mb     max=  670.38 avg=  360.61
  proc_cpu         max=    0.13 avg=    0.07
  sys_cpu          max=    0.67 avg=    0.46
  gc_count         delta=    4.00  (first=87.0 last=91.0)
  gc_sum_s         delta=    0.01  (first=0.281 last=0.29)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=17982.00  (first=119946.0 last=137928.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 7233.00  (first=50312.0 last=57545.0)
  http_count       delta=   40.00  (first=87869.0 last=87909.0)
  gc_max_s         max=0.004
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=9 avg_cpu=67.4% max_cpu=95.9%
ticketqa-prometheus    samples=9 avg_cpu=0.1% max_cpu=0.8%
ticketqa-rabbitmq      samples=9 avg_cpu=21.5% max_cpu=85.0%
ticketqa-redis         samples=9 avg_cpu=5.7% max_cpu=9.8%
ticketqa-wiremock      samples=9 avg_cpu=1.2% max_cpu=3.2%
```
