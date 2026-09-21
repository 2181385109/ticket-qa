# 压测轮次 fix_grab_t200

脚本 `grab_throughput.jmx`,线程 200,ramp-up 40s,持续 60s,额外参数 `-JidsCsv=results/ticket_ids.csv`,执行时间 2026-09-21 01:57:59
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:56:40(fix_grab_t200 之前) |
| 服务版本 | git 0b54afe,JVM uptime 872 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.4391255s,timeout_total 0 |
| JVM 堆已用 / 上限 | 92.6 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 103 次 / 0.314 s / 0.003 s |
| JVM 线程(live / blocked) | 276.0 / 0.0 |
| SLA 后台任务 | 扫描累计 28.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 5.1 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 196402 / 87190 / 66723;按状态 PENDING=87190 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 196432.0 / 66684.0 / 0.0;{'q.ticket.assigned': 38273, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 93722} |
| HTTP 请求累计 | 88002.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-21 01:57:58(fix_grab_t200 之后) |
| 服务版本 | git 0b54afe,JVM uptime 950 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 1.0616614s,timeout_total 0 |
| JVM 堆已用 / 上限 | 378.8 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 114 次 / 0.335 s / 0.003 s |
| JVM 线程(live / blocked) | 275.0 / 0.0 |
| SLA 后台任务 | 扫描累计 31.0 轮,升级累计 0.0;库内待升级积压 0 张,下一批到期 3.8 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 87190 / 225670 / 87190 / 74257;按状态 ASSIGNED=29268,PENDING=57922 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 254968.0 / 74215.0 / 0.0;{'q.ticket.assigned': 63469, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 118910} |
| HTTP 请求累计 | 88098.0 |

## JMeter 结果

```
fix_grab_t200.jtl: samples=29268 wall=60.3s qps=485.8 avg=275.0 p50=308 p95=404 p99=426 max=1103 errors=0 (0.00%) codes={'200': 29268}

fix_grab_t200.jtl label 分布:
   29268  grab | http=200 code=0 status=ASSIGNED
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/fix_grab_t200_metrics.csv: 73 samples 01:56:41..01:57:58
  hikari_active    max=   20.00 avg=   15.33
  hikari_pending   max=  181.00 avg=   88.97
  jvm_threads      max=  277.00 avg=  276.14
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   38.00 avg=   31.15
  heap_used_mb     max=  676.57 avg=  356.44
  proc_cpu         max=    0.13 avg=    0.09
  sys_cpu          max=    0.72 avg=    0.50
  gc_count         delta=   11.00  (first=103.0 last=114.0)
  gc_sum_s         delta=    0.02  (first=0.314 last=0.335)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=58536.00  (first=196432.0 last=254968.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 7261.00  (first=66852.0 last=74113.0)
  http_count       delta=   93.00  (first=88004.0 last=88097.0)
  gc_max_s         max=0.003
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=19 avg_cpu=75.3% max_cpu=96.2%
ticketqa-prometheus    samples=19 avg_cpu=0.1% max_cpu=0.8%
ticketqa-rabbitmq      samples=19 avg_cpu=22.4% max_cpu=86.8%
ticketqa-redis         samples=19 avg_cpu=7.7% max_cpu=9.8%
ticketqa-wiremock      samples=19 avg_cpu=0.7% max_cpu=4.4%
```
