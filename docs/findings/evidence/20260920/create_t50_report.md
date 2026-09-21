# 压测轮次 create_t50

脚本 `ticket_create.jmx`,线程 50,ramp-up 10s,持续 60s,额外参数 ``,执行时间 2026-09-20 19:09:23
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:08:05(create_t50 之前) |
| 服务版本 | git 92ac612,JVM uptime 4418 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 0.0189456s,timeout_total 0 |
| JVM 堆已用 / 上限 | 522.0 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 43 次 / 0.274 s / 0.005 s |
| JVM 线程(live / blocked) | 122.0 / 0.0 |
| SLA 后台任务 | 扫描累计 145.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 12.2 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 25321 / 25321 / 25321 / 19560;按状态 PENDING=25321 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 39739.0 / 33939.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 6698} |
| HTTP 请求累计 | 34323.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:09:22(create_t50 之后) |
| 服务版本 | git 92ac612,JVM uptime 4496 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 0.2049813s,timeout_total 0 |
| JVM 堆已用 / 上限 | 272.1 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 62 次 / 0.31 s / 0.003 s |
| JVM 线程(live / blocked) | 166.0 / 0.0 |
| SLA 后台任务 | 扫描累计 148.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 10.9 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 46716 / 46716 / 46716 / 24666;按状态 PENDING=46716 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 61134.0 / 39038.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 23423} |
| HTTP 请求累计 | 55799.0 |

## JMeter 结果

```
create_t50.jtl: samples=21395 wall=60.0s qps=356.5 avg=127.5 p50=123 p95=177 p99=219 max=357 errors=0 (0.00%) codes={'201': 21395}

create_t50.jtl label 分布:
    6419  create | http=201 code=0 category=TECH priority=P0
    6418  create | http=201 code=0 category=OTHER priority=P2
    4280  create | http=201 code=0 category=REFUND priority=P1
    4278  create | http=201 code=0 category=BILLING priority=P1
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/create_t50_metrics.csv: 73 samples 19:08:05..19:09:22
  hikari_active    max=   20.00 avg=   14.05
  hikari_pending   max=   19.00 avg=    8.07
  jvm_threads      max=  167.00 avg=  156.44
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   69.00 avg=   57.25
  heap_used_mb     max=  672.51 avg=  365.64
  proc_cpu         max=    0.15 avg=    0.10
  sys_cpu          max=    0.67 avg=    0.50
  gc_count         delta=   19.00  (first=43.0 last=62.0)
  gc_sum_s         delta=    0.04  (first=0.274 last=0.31)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=21395.00  (first=39739.0 last=61134.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 5015.00  (first=34020.0 last=39035.0)
  http_count       delta=21474.00  (first=34324.0 last=55798.0)
  gc_max_s         max=0.005
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=78.1% max_cpu=99.7%
ticketqa-prometheus    samples=18 avg_cpu=0.4% max_cpu=4.2%
ticketqa-rabbitmq      samples=18 avg_cpu=23.6% max_cpu=86.7%
ticketqa-redis         samples=18 avg_cpu=2.8% max_cpu=5.7%
ticketqa-wiremock      samples=18 avg_cpu=33.0% max_cpu=64.0%
```
