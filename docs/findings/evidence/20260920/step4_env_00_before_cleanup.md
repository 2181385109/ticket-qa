| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:01:12(清库前) |
| 服务版本 | git 92ac612,JVM uptime 4005 s |
| HikariCP total/idle/active/pending(max) | 4/4/0/0 (20);acquire_max 0.0097041s,timeout_total 0 |
| JVM 堆已用 / 上限 | 544.4 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 16 次 / 0.19 s / 0.0 s |
| JVM 线程(live / blocked) | 96.0 / 0.0 |
| SLA 后台任务 | 扫描累计 132.0 轮,升级累计 2875.0;库内待升级积压 2875 张,下一批到期 177.8 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 8246 / 11332 / 8246 / 14418;按状态 ASSIGNED=33,ESCALATED=2875,PENDING=5338 |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=5 |
| MySQL 慢日志 | slow_query_log=ON long_query_time=0.000000 log_output=TABLE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 14418.0 / 14418.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 8731.0 |
