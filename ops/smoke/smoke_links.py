# 联调冒烟脚本(SLA 升级 / MQ 去重 / 熔断)。需要 wsl + docker exec 进 mysql 改数据。
# 用法:python ops/smoke/smoke_links.py ;熔断段会让 LLM 熔断 60 秒,跑完等一分钟再做别的。
import json, sys, io, time, subprocess, urllib.request, urllib.error, base64
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://localhost:8080"
FAILS = []

def call(method, path, user=None, body=None, expect=None, label=""):
    h = {"Content-Type": "application/json; charset=utf-8"}
    if user is not None: h["X-User-Id"] = str(user)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r: status, text = r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e: status, text = e.code, e.read().decode("utf-8")
    js = json.loads(text) if text else None
    ok = "" if expect is None else ("  OK" if status == expect else f"  !!! expected {expect}")
    print(f"[{label}] {method} {path} user={user} -> HTTP {status} {int((time.time()-t0)*1000)}ms{ok}")
    if expect is not None and status != expect: FAILS.append(label)
    return js["data"] if js and "data" in js else js

def sql(q):
    cmd = ["wsl.exe", "-d", "Ubuntu-24.04", "-u", "root", "--", "docker", "exec", "ticketqa-mysql",
           "mysql", "-uticketqa", "-pticketqa123", "ticket_qa", "-N", "-e", q]
    out = subprocess.run(cmd, capture_output=True).stdout.decode("utf-16-le", errors="ignore") if False else subprocess.run(cmd, capture_output=True).stdout
    txt = out.decode("utf-8", errors="ignore").replace("\x00", "")
    return [l.split("\t") for l in txt.splitlines() if l.strip() and not l.startswith("wsl:") and "localhost" not in l]

def metric(name):
    with urllib.request.urlopen(BASE + "/actuator/prometheus", timeout=10) as r: txt = r.read().decode()
    return [l for l in txt.splitlines() if l.startswith(name)]

print("=== A. SLA 自动升级:闭区间 + 防重复 ===")
t = call("POST", "/api/tickets", user=1, body={"title": "登录报错 紧急", "content": "无法登录", "customerId": 3001}, expect=201, label="create P0")
tid = t["id"]; print("    ticket", tid, t["priority"], "deadline", t["slaDeadline"])
# 把截止时间改到"现在"(闭区间:等于即超时)——用 MySQL 的 NOW(3) 与应用同一时区
sql(f"UPDATE ticket SET sla_deadline = NOW(3) WHERE id = {tid}")
time.sleep(0.2)
r1 = call("POST", "/api/admin/sla/scan", user=1, expect=200, label="scan #1 (deadline == now)")
print("    escalated:", r1)
assert r1["escalated"] >= 1, r1
tk = call("GET", f"/api/tickets/{tid}", user=1, expect=200, label="get after scan")
assert tk["status"] == "ESCALATED" and tk.get("escalatedAt"), tk
r2 = call("POST", "/api/admin/sla/scan", user=1, expect=200, label="scan #2 (must be 0)")
assert r2["escalated"] == 0, r2
logs = call("GET", f"/api/tickets/{tid}/audit-logs", user=1, expect=200, label="audit")
sched = [l for l in logs if l["source"] == "SCHEDULER"]
print("    SCHEDULER 审计条数:", len(sched), "|", sched[0]["remark"][:80] if sched else "-")
assert len(sched) == 1
# ESCALATED → ASSIGNED 后再扫,不能第二次升级(escalated_at 永久标记)
a = call("POST", f"/api/tickets/{tid}/assign", user=2, body={"assigneeId": 3}, expect=200, label="leader assign ESCALATED->ASSIGNED")
assert a["status"] == "ASSIGNED"
r3 = call("POST", "/api/admin/sla/scan", user=1, expect=200, label="scan #3 after reassign (must be 0)")
assert r3["escalated"] == 0, r3
rows = sql(f"SELECT status, escalated_at IS NOT NULL FROM ticket WHERE id = {tid}")
print("    db:", rows)
print("    sla metrics:", metric("sla_escalated_total"), metric("sla_escalation_skipped_total"))

print("\n=== B. MQ:去重表 + 重复投递 ===")
time.sleep(1.5)
rows = sql(f"SELECT consumer, event_type, message_id FROM mq_message_dedup WHERE ticket_id = {tid} ORDER BY id")
for r in rows: print("    dedup:", r)
kinds = {r[1] for r in rows}
assert "SLA_ESCALATED" in kinds and "STATUS_CHANGED" in kinds and "ASSIGNED" in kinds, kinds
# 通过 RabbitMQ 管理 API 把同一条 SLA_ESCALATED 消息再投递一次(相同 messageId)
sla_row = [r for r in rows if r[1] == "SLA_ESCALATED"][0]
mid = sla_row[2]
payload = {"messageId": mid, "eventType": "SLA_ESCALATED", "ticketId": tid, "ticketNo": t["ticketNo"],
           "fromStatus": "PENDING", "toStatus": "ESCALATED", "operatorName": "SCHEDULER", "source": "SCHEDULER",
           "traceId": "dup-test", "occurredAt": "2026-09-20 00:00:00"}
body = {"properties": {"content_type": "application/json",
                       "headers": {"__TypeId__": "com.ticketqa.mq.message.TicketEventMessage"}},
        "routing_key": "ticket.sla.escalated", "payload": json.dumps(payload), "payload_encoding": "string"}
req = urllib.request.Request("http://localhost:15672/api/exchanges/%2F/ticket.events/publish", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json",
                                      "Authorization": "Basic " + base64.b64encode(b"ticketqa:rabbit123").decode()}, method="POST")
before = metric("mq_event_duplicate_total")
with urllib.request.urlopen(req, timeout=10) as r: print("    republish via mgmt api:", r.read().decode())
time.sleep(2)
after = metric("mq_event_duplicate_total")
print("    duplicate metric before:", before, "after:", after)
cnt = sql(f"SELECT COUNT(*) FROM mq_message_dedup WHERE message_id = '{mid}'")
print("    dedup rows for messageId:", cnt)
assert cnt[0][0] == "1", cnt
assert after and after[0].endswith(" 1.0") or (before and after and float(after[0].split()[-1]) == float(before[0].split()[-1]) + 1), (before, after)

print("\n=== C. 熔断:连续 5 次 [ERROR] → 打开 60s → 直接走规则 ===")
for i in range(5):
    call("POST", "/api/tickets", user=1, body={"title": f"[ERROR] 退款 {i}", "content": "x", "customerId": 4000 + i}, expect=201, label=f"[ERROR] #{i+1}")
print("    circuit_open:", metric("llm_circuit_open_total"), "state:", metric("llm_circuit_state"))
assert metric("llm_circuit_state")[0].endswith(" 1.0")
c = call("POST", "/api/tickets", user=1, body={"title": "账单问题", "content": "正常请求,但熔断打开", "customerId": 4100}, expect=201, label="create while OPEN")
rows = sql(f"SELECT degraded, degrade_reason, final_category, latency_ms FROM llm_call_log WHERE ticket_id = {c['id']}")
print("    llm_call_log:", rows)
assert rows[0][1] == "CIRCUIT_OPEN" and rows[0][2] == "BILLING", rows
print("    fallback metrics:", *metric("llm_fallback_total"), sep="\n      ")

print("\n=== D. llm_call_log 与工单绑定、响应模型名 ===")
rows = sql("SELECT COUNT(*), SUM(ticket_id IS NULL), SUM(degraded), SUM(response_model IS NOT NULL) FROM llm_call_log")
print("    total / unbound / degraded / with_response_model:", rows)
assert rows[0][1] == "0", "所有分类记录都应绑定 ticket_id"

print("\n=== RESULT ===")
print("FAILS:", FAILS if FAILS else "none")
