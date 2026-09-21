"""导出仍为 PENDING 的 P1/P2 工单 id 到 results/ticket_ids.csv,供 grab_throughput.jmx 用(每轮前重导,避免重复抢;只取 group_id=1,agents.csv 里的坐席 3、4 在 1 组,否则 403)。"""
import pymysql, sys
c = pymysql.connect(host='127.0.0.1', user='ticketqa', password='ticketqa123', database='ticket_qa')
cur = c.cursor()
cur.execute("SELECT id FROM ticket WHERE status='PENDING' AND group_id=1 AND escalated_at IS NULL ORDER BY id")
ids = [r[0] for r in cur.fetchall()]
out = sys.argv[1] if len(sys.argv) > 1 else 'results/ticket_ids.csv'
with open(out, 'w') as f:
    f.write('ticketId\n' + '\n'.join(map(str, ids)) + '\n')
print(f"exported {len(ids)} ids -> {out}")
