# 压测轮次 grab_t100

脚本 `grab_throughput.jmx`,线程 100,ramp-up 20s,持续 60s,额外参数 ``,执行时间 2026-09-20 19:29:17
JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)

## 环境状态(压测前)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:27:59(grab_t100 之前) |
| 服务版本 | git 92ac612,JVM uptime 5612 s |
| HikariCP total/idle/active/pending(max) | 19/19/0/0 (20);acquire_max 0.0004932s,timeout_total 0 |
| JVM 堆已用 / 上限 | 361.0 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 162 次 / 0.536 s / 0.003 s |
| JVM 线程(live / blocked) | 96.0 / 0.0 |
| SLA 后台任务 | 扫描累计 184.0 轮,升级累计 4275.0;库内待升级积压 25790 张,下一批到期 37.2 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 169182 / 90629 / 247737;按状态 ESCALATED=1400,PENDING=89227 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=20 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 262155.0 / 262155.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 100528.0 |

## 环境状态(压测后)

| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:29:17(grab_t100 之后) |
| 服务版本 | git 92ac612,JVM uptime 5690 s |
| HikariCP total/idle/active/pending(max) | 20/19/1/0 (20);acquire_max 0.5041219s,timeout_total 0 |
| JVM 堆已用 / 上限 | 575.6 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 175 次 / 0.569 s / 0.004 s |
| JVM 线程(live / blocked) | 187.0 / 0.0 |
| SLA 后台任务 | 扫描累计 186.0 轮,升级累计 4475.0;库内待升级积压 25590 张,下一批到期 36.0 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 90627 / 198754 / 90629 / 254493;按状态 ASSIGNED=29274,ESCALATED=1600,PENDING=59753 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=21 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 321299.0 / 268826.0 / 0.0;{'q.ticket.assigned': 27670, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 27873} |
| HTTP 请求累计 | 100610.0 |

## JMeter 结果

```
grab_t100.jtl: samples=29372 wall=60.1s qps=488.8 avg=167.8 p50=189 p95=216 p99=258 max=545 errors=0 (0.00%) codes={'200': 29372}

grab_t100.jtl label 分布:
   29372  grab | http=200 code=0 status=ASSIGNED
```

## 服务侧指标(每秒采样,峰值 / 均值 / 差分)

```
results/grab_t100_metrics.csv: 73 samples 19:27:59..19:29:16
  hikari_active    max=   20.00 avg=   15.30
  hikari_pending   max=   84.00 avg=   49.01
  jvm_threads      max=  189.00 avg=  171.07
  threads_blocked  max=    0.00 avg=    0.00
  threads_runnable max=   61.00 avg=   54.66
  heap_used_mb     max=  689.00 avg=  385.84
  proc_cpu         max=    0.12 avg=    0.08
  sys_cpu          max=    0.63 avg=    0.46
  gc_count         delta=   13.00  (first=162.0 last=175.0)
  gc_sum_s         delta=    0.03  (first=0.536 last=0.569)
  llm_fallback     delta=    0.00  (first=0.0 last=0.0)
  llm_circuit_open delta=    0.00  (first=0.0 last=0.0)
  mq_published     delta=59144.00  (first=262155.0 last=321299.0)
  mq_publish_failed delta=    0.00  (first=0.0 last=0.0)
  mq_consumed      delta= 6629.00  (first=262155.0 last=268784.0)
  http_count       delta=   80.00  (first=100529.0 last=100609.0)
  gc_max_s         max=0.004
```

## 容器 CPU(docker stats,每 ~4 s 一次)

```
ticketqa-mysql         samples=18 avg_cpu=74.7% max_cpu=98.5%
ticketqa-prometheus    samples=18 avg_cpu=0.3% max_cpu=2.8%
ticketqa-rabbitmq      samples=18 avg_cpu=24.0% max_cpu=92.7%
ticketqa-redis         samples=18 avg_cpu=3.4% max_cpu=6.0%
ticketqa-wiremock      samples=18 avg_cpu=0.9% max_cpu=7.5%
```
