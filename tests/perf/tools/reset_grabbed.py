"""把被抢过的工单重置回 PENDING(仅用于吞吐压测复用同一批工单)。

重置同时给每张单补一条审计 ASSIGNED→PENDING(source=MANUAL,remark='perf reset'),
否则审计序列会断裂(上一行 to=ASSIGNED,下一次抢单的 from=PENDING),tests/api/test_audit_chain.py 的
全库扫描会把压测工具制造的断裂误报成服务缺陷。version 不动:条件更新只要求它和 SELECT 读到的一致。
"""
import pymysql
c = pymysql.connect(host='127.0.0.1', user='ticketqa', password='ticketqa123', database='ticket_qa', autocommit=False)
cur = c.cursor()
cur.execute("""INSERT INTO ticket_audit_log (ticket_id, from_status, to_status, operator_id, operator_name, source, remark, trace_id, created_at)
               SELECT id, 'ASSIGNED', 'PENDING', 1, 'perf-tool', 'MANUAL', 'perf reset', 'perf-reset', NOW(3)
                 FROM ticket WHERE status='ASSIGNED'""")
n = cur.execute("UPDATE ticket SET status='PENDING', assignee_id=NULL, updated_at=NOW(3) WHERE status='ASSIGNED'")
c.commit()
print(f"reset {n} ASSIGNED -> PENDING (+{n} audit rows)")
