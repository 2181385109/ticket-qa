# 压测轮次 grab_t200

脚本 `grab_throughput.jmx`,线程 200,ramp-up 40s,持续 60s,额外参数 ``,执行时间 2026-09-20 19:30:41
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:29:22(grab_t200 之前) |
| 服务版本 | git 92ac612,JVM uptime 5696 s |
| HikariCP total/idle/active/pending(max) | 20/18/2/0 (20);acquire_max 0.5041219s,timeout_total 0 |
| JVM 堆已用 / 上限 | 135.9 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 176 次 / 0.572 s / 0.004 s |
| JVM 线程(live / blocked) | 187.0 / 0.0 |
| SLA 后台任务 | 扫描累计 186.0 轮,升级累计 4475.0;库内待升级积压 25590 张,下一批到期 35.9 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 198754 / 90629 / 256464;按状态 ESCALATED=1600,PENDING=89027 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 321299.0 / 270809.0 / 0.0;{'q.ticket.assigned': 25891, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 26097} |
| HTTP 请求累计 | 100617.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:30:40(grab_t200 之后) |
| 服务版本 | git 92ac612,JVM uptime 5774 s |
| HikariCP total/idle/active/pending(max) | 20/17/3/0 (20);acquire_max 0.9309287s,timeout_total 0 |
| JVM 堆已用 / 上限 | 689.5 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 189 次 / 0.602 s / 0.004 s |
| JVM 线程(live / blocked) | 286.0 / 0.0 |
| SLA 后台任务 | 扫描累计 189.0 轮,升级累计 4756.0;库内待升级积压 25290 张,下一批到期 34.6 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 229136 / 90629 / 264132;按状态 ASSIGNED=29983,ESCALATED=1900,PENDING=58744 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 382025.0 / 278456.0 / 0.0;{'q.ticket.assigned': 52732, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 53167} |
| HTTP 请求累计 | 100709.0 |

## JMeter 结果

```
grab_t200.jtl: samples=30127 wall=60.2s qps=500.5 avg=267.0 p50=299 p95=393 p99=450 max=973 errors=45 (0.15%) codes={'200': 30082, '409': 45}

grab_t200.jtl label 分布:
   30082  grab | http=200 code=0 status=ASSIGNED
      45  grab | http=409 code=40901 status=-
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/grab_t200_metrics.csv: 74 samples 19:29:23..19:30:41
  hikari_active    max=   20.00 avg=   15.34
  hikari_pending   max=  183.00 avg=   88.86
  jvm_threads      max=  288.00 avg=  244.73
  threads_blocked  max=    1.00 avg=    0.01
  threads_runnable max=   61.00 avg=   55.03
  heap_used_mb     max=  684.94 avg=  389.41
  proc_cpu         max=    0.13 avg=    0.09
  sys_cpu          max=    0.70 avg=    0.48
  gc_count         delta=   14.00  (first=176.0 last=190.0)
  gc_sum_s         delta=    0.03  (first=0.572 last=0.605)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=60764.00  (first=321299.0 last=382063.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 7544.00  (first=271004.0 last=278548.0)
  http_count       delta=   91.00  (first=100619.0 last=100710.0)
  gc_max_s         max=0.004
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=74.9% max_cpu=92.9%
ticketqa-prometheus    samples=18 avg_cpu=0.1% max_cpu=0.8%
ticketqa-rabbitmq      samples=18 avg_cpu=27.1% max_cpu=89.5%
ticketqa-redis         samples=18 avg_cpu=3.5% max_cpu=6.5%
ticketqa-wiremock      samples=18 avg_cpu=0.6% max_cpu=2.8%
```
