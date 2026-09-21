# 压测轮次 grab_t10

脚本 `grab_throughput.jmx`,线程 10,ramp-up 2s,持续 20s,额外参数 ``,执行时间 2026-09-20 19:22:42
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:22:05(grab_t10 之前) |
| 服务版本 | git 92ac612,JVM uptime 5258 s |
| HikariCP total/idle/active/pending(max) | 20/20/0/0 (20);acquire_max 0.0098935s,timeout_total 0 |
| JVM 堆已用 / 上限 | 575.8 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 130 次 / 0.469 s / 0.002 s |
| JVM 线程(live / blocked) | 108.0 / 0.0 |
| SLA 后台任务 | 扫描累计 173.0 轮,升级累计 3175.0;库内待升级积压 3907 张,下一批到期 0.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 122578 / 90629 / 154529;按状态 ESCALATED=300,PENDING=90327 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 168947.0 / 168947.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 100245.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:22:42(grab_t10 之后) |
| 服务版本 | git 92ac612,JVM uptime 5296 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.0098935s,timeout_total 0 |
| JVM 堆已用 / 上限 | 379.0 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 135 次 / 0.479 s / 0.002 s |
| JVM 线程(live / blocked) | 108.0 / 0.0 |
| SLA 后台任务 | 扫描累计 174.0 轮,升级累计 3275.0;库内待升级积压 6974 张,下一批到期 0.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 131157 / 90629 / 163212;按状态 ASSIGNED=8431,ESCALATED=400,PENDING=81796 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 186105.0 / 177544.0 / 0.0;{'q.ticket.assigned': 5863, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 5975} |
| HTTP 请求累计 | 100285.0 |

## JMeter 结果

```
grab_t10.jtl: samples=8479 wall=19.9s qps=425.8 avg=21.7 p50=22 p95=26 p99=28 max=38 errors=0 (0.00%) codes={'200': 8479}

grab_t10.jtl label 分布:
    8479  grab | http=200 code=0 status=ASSIGNED
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/grab_t10_metrics.csv: 35 samples 19:22:05..19:22:41
  hikari_active    max=   14.00 avg=    6.49
  hikari_pending   max=    0.00 avg=    0.00
  jvm_threads      max=  109.00 avg=  108.37
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   61.00 avg=   54.11
  heap_used_mb     max=  687.23 avg=  383.83
  proc_cpu         max=    0.12 avg=    0.06
  sys_cpu          max=    0.60 avg=    0.40
  gc_count         delta=    5.00  (first=130.0 last=135.0)
  gc_sum_s         delta=    0.01  (first=0.469 last=0.479)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=17158.00  (first=168947.0 last=186105.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 8359.00  (first=168947.0 last=177306.0)
  http_count       delta=   38.00  (first=100246.0 last=100284.0)
  gc_max_s         max=0.002
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=8 avg_cpu=63.8% max_cpu=90.5%
ticketqa-prometheus    samples=8 avg_cpu=0.1% max_cpu=0.6%
ticketqa-rabbitmq      samples=8 avg_cpu=10.8% max_cpu=9.9%
ticketqa-redis         samples=8 avg_cpu=2.5% max_cpu=5.8%
ticketqa-wiremock      samples=8 avg_cpu=0.5% max_cpu=3.1%
```
