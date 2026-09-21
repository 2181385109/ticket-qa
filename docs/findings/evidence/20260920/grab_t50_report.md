# 压测轮次 grab_t50

脚本 `grab_throughput.jmx`,线程 50,ramp-up 10s,持续 20s,额外参数 ``,执行时间 2026-09-20 19:24:08
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:23:30(grab_t50 之前) |
| 服务版本 | git 92ac612,JVM uptime 5343 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.0564941s,timeout_total 0 |
| JVM 堆已用 / 上限 | 631.1 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 140 次 / 0.489 s / 0.002 s |
| JVM 线程(live / blocked) | 108.0 / 0.0 |
| SLA 后台任务 | 扫描累计 176.0 轮,升级累计 3475.0;库内待升级积压 9131 张,下一批到期 0.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 140357 / 90629 / 175495;按状态 ESCALATED=600,PENDING=90027 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 204505.0 / 189825.0 / 0.0;{'q.ticket.assigned': 8460, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 8782} |
| HTTP 请求累计 | 100329.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:24:07(grab_t50 之后) |
| 服务版本 | git 92ac612,JVM uptime 5381 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.1903417s,timeout_total 0 |
| JVM 堆已用 / 上限 | 597.3 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 145 次 / 0.499 s / 0.002 s |
| JVM 线程(live / blocked) | 137.0 / 0.0 |
| SLA 后台任务 | 扫描累计 177.0 轮,升级累计 3575.0;库内待升级积压 13208 张,下一批到期 0.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 149750 / 90629 / 183103;按状态 ASSIGNED=9243,ESCALATED=700,PENDING=80684 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 223291.0 / 197432.0 / 0.0;{'q.ticket.assigned': 13471, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 13898} |
| HTTP 请求累计 | 100369.0 |

## JMeter 结果

```
grab_t50.jtl: samples=9293 wall=20.0s qps=465.5 avg=80.7 p50=94 p95=108 p99=127 max=229 errors=0 (0.00%) codes={'200': 9293}

grab_t50.jtl label 分布:
    9293  grab | http=200 code=0 status=ASSIGNED
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/grab_t50_metrics.csv: 36 samples 19:23:30..19:24:08
  hikari_active    max=   20.00 avg=   10.22
  hikari_pending   max=   34.00 avg=   10.92
  jvm_threads      max=  138.00 avg=  129.39
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   67.00 avg=   54.44
  heap_used_mb     max=  682.10 avg=  386.26
  proc_cpu         max=    0.12 avg=    0.07
  sys_cpu          max=    0.60 avg=    0.42
  gc_count         delta=    5.00  (first=140.0 last=145.0)
  gc_sum_s         delta=    0.01  (first=0.489 last=0.499)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=18786.00  (first=204505.0 last=223291.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 7472.00  (first=190014.0 last=197486.0)
  http_count       delta=   40.00  (first=100330.0 last=100370.0)
  gc_max_s         max=0.002
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=9 avg_cpu=64.5% max_cpu=93.2%
ticketqa-prometheus    samples=9 avg_cpu=0.0% max_cpu=0.1%
ticketqa-rabbitmq      samples=9 avg_cpu=23.7% max_cpu=78.9%
ticketqa-redis         samples=9 avg_cpu=2.2% max_cpu=3.8%
ticketqa-wiremock      samples=9 avg_cpu=0.4% max_cpu=2.7%
```
