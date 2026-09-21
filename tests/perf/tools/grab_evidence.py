"""抢单压测后的数据库取证:HTTP 层看不见竞态,要看库。

用法:
    python tools/grab_evidence.py <ticket_id>            # 一张工单的完整证据
    python tools/grab_evidence.py --latest               # 最近一张 "perf grab target" 工单
    python tools/grab_evidence.py --scan                 # 扫全库:哪些工单 audit_log 里 to_status='ASSIGNED' 多于 1 条

四个问题,各对应一条 SQL(原样打印,方便抄进 findings):
    Q1 audit_log 里同一 ticket_id 是否出现多条 to_status='ASSIGNED'
    Q2 ticket 表当前 assignee_id / status / updated_at / version(只能看到终值;被覆盖的证据来自 Q1 的多个 operator_id)
    Q3 审计时间线(毫秒级),用于和 JMeter 的响应对账
    Q4 审计序列连续性(KI-009 的反向断言):按 id 排序后第 k 行 to_status 必须等于第 k+1 行 from_status,
       且终态 status 等于最后一行 to_status——修复前这条在并发抢过的单上必然失败
连接参数默认与 ops/.env.example 一致,可用环境变量 MYSQL_HOST/PORT/USER/PASSWORD/DATABASE 覆盖。
"""
import os
import sys

import pymysql

CONN = dict(
    host=os.getenv("MYSQL_HOST", "127.0.0.1"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "ticketqa"),
    password=os.getenv("MYSQL_PASSWORD", "ticketqa123"),
    database=os.getenv("MYSQL_DATABASE", "ticket_qa"),
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)

Q1 = """SELECT ticket_id, to_status, COUNT(*) AS n, GROUP_CONCAT(operator_id ORDER BY id) AS operators
FROM ticket_audit_log WHERE ticket_id = %s AND to_status = 'ASSIGNED' GROUP BY ticket_id, to_status"""
Q2 = """SELECT id, status, assignee_id, group_id, version, created_at, updated_at FROM ticket WHERE id = %s"""
Q3 = """SELECT id, from_status, to_status, operator_id, operator_name, source, remark, trace_id,
       DATE_FORMAT(created_at, '%%H:%%i:%%s.%%f') AS created_at
FROM ticket_audit_log WHERE ticket_id = %s ORDER BY id"""
Q_SCAN = """SELECT ticket_id, COUNT(*) AS assigned_rows, GROUP_CONCAT(operator_id ORDER BY id) AS operators
FROM ticket_audit_log WHERE to_status = 'ASSIGNED' GROUP BY ticket_id HAVING COUNT(*) > 1 ORDER BY ticket_id"""
Q_LATEST = """SELECT id FROM ticket WHERE title LIKE 'perf grab target%%' ORDER BY id DESC LIMIT 1"""


def run(cur, sql, args=()):
    cur.execute(sql, args)
    rows = cur.fetchall()
    print("SQL> " + " ".join(sql.split()) % tuple(repr(a) for a in args) if args else "SQL> " + " ".join(sql.split()))
    if not rows:
        print("  (0 rows)")
        return rows
    cols = list(rows[0].keys())
    print("  " + " | ".join(cols))
    for r in rows:
        print("  " + " | ".join("" if r[c] is None else str(r[c]) for c in cols))
    return rows


def chain_breaks(rows, final_status=None):
    """Q4:返回断裂点列表 [(id_k, to_k, from_k1)];空列表即连续。final_status 给了就再核对终态。"""
    breaks = []
    for k in range(len(rows) - 1):
        if rows[k]["to_status"] != rows[k + 1]["from_status"]:
            breaks.append((rows[k]["id"], rows[k]["to_status"], rows[k + 1]["from_status"]))
    if final_status is not None and rows and rows[-1]["to_status"] != final_status:
        breaks.append((rows[-1]["id"], rows[-1]["to_status"], f"ticket.status={final_status}"))
    return breaks


def evidence(cur, ticket_id):
    print(f"===== ticket_id={ticket_id} =====")
    q1 = run(cur, Q1, (ticket_id,))
    print()
    q2 = run(cur, Q2, (ticket_id,))
    print()
    q3 = run(cur, Q3, (ticket_id,))
    n_assigned = q1[0]["n"] if q1 else 0
    breaks = chain_breaks(q3, q2[0]["status"] if q2 else None)
    print(f"\n[结论字段] audit_log 里 to_status='ASSIGNED' 的行数 = {n_assigned}  (>1 即重复分配)  审计总行数 = {len(q3)}")
    print(f"[结论字段] 审计序列连续(第k行to==第k+1行from 且 终态==最后一行to)= {'YES' if not breaks else 'NO ' + str(breaks)}")
    return n_assigned


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    conn = pymysql.connect(**CONN)
    try:
        with conn.cursor() as cur:
            if sys.argv[1] == "--scan":
                run(cur, Q_SCAN)
            elif sys.argv[1] == "--latest":
                cur.execute(Q_LATEST)
                row = cur.fetchone()
                if not row:
                    print("no perf grab target ticket")
                    return 1
                evidence(cur, row["id"])
            else:
                evidence(cur, int(sys.argv[1]))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
