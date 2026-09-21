| 环境状态 | 值 |
|---|---|
| 采集时间 | 2026-09-20 19:02:11(清库后基线) |
| 服务版本 | git 92ac612,JVM uptime 4065 s |
| HikariCP total/idle/active/pending(max) | 4/4/0/0 (20);acquire_max 0.0005026s,timeout_total 0 |
| JVM 堆已用 / 上限 | 559.4 / 1024.0 MB |
| GC 累计次数 / 累计停顿 / 单次最大 | 16 次 / 0.19 s / 0.0 s |
| JVM 线程(live / blocked) | 96.0 / 0.0 |
| SLA 后台任务 | 扫描累计 134.0 轮,升级累计 2875.0;库内待升级积压 0 张,下一批到期 None 分钟后 |
| 库内行数 ticket / audit / llm_call_log / mq_dedup | 0 / 0 / 0 / 0;按状态 None |
| MySQL 持久化配置 | innodb_flush_log_at_trx_commit=1 sync_binlog=1 isolation=REPEATABLE-READ lock_wait_timeout=50 buffer_pool=268435456 max_connections=151 threads_connected=5 |
| MySQL 慢日志 | slow_query_log=OFF long_query_time=10.000000 log_output=FILE |
| LLM 熔断 / 降级累计 / 熔断累计 | state=0.0 fallback=0 open=0 |
| MQ 发布 / 消费 / 发布失败;队列积压 | 14418.0 / 14418.0 / 0.0;{'q.ticket.assigned': 0, 'q.ticket.sla-escalated': 0, 'q.ticket.status-changed': 0} |
| HTTP 请求累计 | 8738.0 |
