# 压测轮次 create_t200

脚本 `ticket_create.jmx`,线程 200,ramp-up 40s,持续 60s,额外参数 ``,执行时间 2026-09-20 19:12:32
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:11:14(create_t200 之前) |
| 服务版本 | git 92ac612,JVM uptime 4607 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 0.9822527s,timeout_total 0 |
| JVM 堆已用 / 上限 | 638.3 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 80 次 / 0.352 s / 0.003 s |
| JVM 线程(live / blocked) | 208.0 / 0.0 |
| SLA 后台任务 | 扫描累计 152.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 9.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 68637 / 68637 / 68637 / 35329;按状态 PENDING=68637 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 83055.0 / 49707.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 34982} |
| HTTP 请求累计 | 77821.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:12:32(create_t200 之后) |
| 服务版本 | git 92ac612,JVM uptime 4685 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 2.8185951s,timeout_total 0 |
| JVM 堆已用 / 上限 | 615.9 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 97 次 / 0.406 s / 0.004 s |
| JVM 线程(live / blocked) | 305.0 / 0.0 |
| SLA 后台任务 | 扫描累计 154.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 7.7 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 90627 / 90629 / 39620;按状态 PENDING=90627 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 105045.0 / 53998.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 52279} |
| HTTP 请求累计 | 99905.0 |

## JMeter 结果

```
create_t200.jtl: samples=21992 wall=60.3s qps=364.7 avg=366.8 p50=301 p95=911 p99=1346 max=2916 errors=2 (0.01%) codes={'201': 21990, '500': 2}

create_t200.jtl label 分布:
    6598  create | http=201 code=0 category=TECH priority=P0
    6596  create | http=201 code=0 category=OTHER priority=P2
    4398  create | http=201 code=0 category=BILLING priority=P1
    4398  create | http=201 code=0 category=REFUND priority=P1
       2  create | http=500 code=50000 category=- priority=-
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/create_t200_metrics.csv: 73 samples 19:11:15..19:12:32
  hikari_active    max=   20.00 avg=   14.45
  hikari_pending   max=  167.00 avg=   76.40
  jvm_threads      max=  306.00 avg=  263.38
  threads_blocked  max=    1.00 avg=    0.01
  threads_runnable max=   70.00 avg=   57.97
  heap_used_mb     max=  666.29 avg=  388.66
  proc_cpu         max=    0.22 avg=    0.10
  sys_cpu          max=    0.75 avg=    0.50
  gc_count         delta=   17.00  (first=80.0 last=97.0)
  gc_sum_s         delta=    0.05  (first=0.352 last=0.406)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=21990.00  (first=83055.0 last=105045.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 4149.00  (first=49791.0 last=53940.0)
  http_count       delta=22082.00  (first=77822.0 last=99904.0)
  gc_max_s         max=0.004
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=75.2% max_cpu=99.3%
ticketqa-prometheus    samples=18 avg_cpu=0.1% max_cpu=0.6%
ticketqa-rabbitmq      samples=18 avg_cpu=17.8% max_cpu=9.2%
ticketqa-redis         samples=18 avg_cpu=3.0% max_cpu=5.9%
ticketqa-wiremock      samples=18 avg_cpu=51.0% max_cpu=80.8%
```
