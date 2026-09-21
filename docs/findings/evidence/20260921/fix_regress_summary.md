# 抢单竞态回归(fix)2026-09-21 01:44:19

服务 {"status":"UP","components":{"db":{"stat / 修复代码 git 0b54afe

| 轮次 | 线程 | 压测前池 | HTTP 200 | HTTP 409 | 其他 | 审计 ASSIGNED 行数 | 审计序列连续 | Δlock_acquired | Δlock_rejected | Δlock_unavailable | Δdb_conflict | Δversion_conflict | 工单 id |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fix_r1 | 2 | hikaricp_connections=2.0 hikaricp_connections_active=0.0 hikaricp_connections_idle=2.0  | 1 | 1 | 0 | 1 | YES | 1 | 1 | 0 | 0 | 0 | 4334 |
| fix_r2 | 2 | hikaricp_connections=2.0 hikaricp_connections_active=0.0 hikaricp_connections_idle=2.0  | 1 | 1 | 0 | 1 | YES | 1 | 1 | 0 | 0 | 0 | 4335 |
| fix_r3 | 2 | hikaricp_connections=2.0 hikaricp_connections_active=0.0 hikaricp_connections_idle=2.0  | 1 | 1 | 0 | 1 | YES | 1 | 1 | 0 | 0 | 0 | 4336 |
| fix_r4 | 2 | hikaricp_connections=2.0 hikaricp_connections_active=0.0 hikaricp_connections_idle=2.0  | 1 | 1 | 0 | 1 | YES | 1 | 1 | 0 | 0 | 0 | 4337 |
| fix_r5 | 2 | hikaricp_connections=2.0 hikaricp_connections_active=0.0 hikaricp_connections_idle=2.0  | 1 | 1 | 0 | 1 | YES | 1 | 1 | 0 | 0 | 0 | 4338 |
| fix_r1 | 20 | hikaricp_connections=3.0 hikaricp_connections_active=0.0 hikaricp_connections_idle=3.0  | 1 | 19 | 0 | 1 | YES | 1 | 19 | 0 | 0 | 0 | 4339 |
| fix_r1 | 100 | hikaricp_connections=3.0 hikaricp_connections_active=0.0 hikaricp_connections_idle=3.0  | 1 | 99 | 0 | 1 | YES | 2 | 98 | 0 | 0 | 0 | 4340 |

全库扫描(to_status='ASSIGNED' 多于 1 行的工单):
```
SQL> SELECT ticket_id, COUNT(*) AS assigned_rows, GROUP_CONCAT(operator_id ORDER BY id) AS operators FROM ticket_audit_log WHERE to_status = 'ASSIGNED' GROUP BY ticket_id HAVING COUNT(*) > 1 ORDER BY ticket_id
  (0 rows)
```
