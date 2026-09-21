# 联调冒烟脚本(接口逐个跑通)。这不是测试体系的一部分——下一阶段由 tests/api 的 pytest 取代。
# 用法:服务启动后  python ops/smoke/smoke_api.py   (Windows 建议先 set PYTHONIOENCODING=utf-8)
import json, sys, urllib.request, urllib.error, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
BASE = "http://localhost:8080"

def call(method, path, user=None, body=None, raw=None, headers=None, expect=None, label=""):
    h = {"Content-Type": "application/json; charset=utf-8"}
    if user is not None: h["X-User-Id"] = str(user)
    if headers: h.update(headers)
    data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            status, text = r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode("utf-8")
    ms = int((time.time() - t0) * 1000)
    try: js = json.loads(text)
    except Exception: js = None
    code = js.get("code") if isinstance(js, dict) else None
    mark = "" if expect is None else ("  OK" if status == expect else f"  !!! expected {expect}")
    print(f"[{label}] {method} {path} user={user} -> HTTP {status} code={code} {ms}ms{mark}")
    if js is not None:
        d = js.get("data") if isinstance(js, dict) else None
        show = d if d is not None else js
        s = json.dumps(show, ensure_ascii=False)
        print("    " + (s if len(s) < 400 else s[:400] + "..."))
    else:
        print("    " + text[:300])
    if expect is not None and status != expect:
        print("    >>> MISMATCH"); FAILS.append(label)
    return status, js

FAILS = []
def data(js): return js["data"]

print("=== 0. 健康与鉴权 ===")
call("GET", "/actuator/health", expect=200, label="health")
call("GET", "/api/agents/me", expect=401, label="no header -> 401")
call("GET", "/api/agents/me", user=999, expect=401, label="unknown user -> 401")
call("GET", "/api/agents/me", user=3, expect=200, label="agent_a me")

print("\n=== 1. 创建工单 → 触发 LLM 分类(挡板) ===")
_, t1 = call("POST", "/api/tickets", user=1, body={"title": "申请退款", "content": "订单 123 重复扣款,请退款", "customerId": 1001}, expect=201, label="create REFUND")
_, t2 = call("POST", "/api/tickets", user=1, body={"title": "登录报错", "content": "App 崩溃无法登录", "customerId": 1002}, expect=201, label="create TECH/P0")
_, t3 = call("POST", "/api/tickets", user=1, body={"title": "咨询会员权益", "content": "想了解一下", "customerId": 1003, "groupId": 2}, expect=201, label="create OTHER group2")
call("POST", "/api/tickets", user=1, body={"title": "", "content": "x", "customerId": 1}, expect=400, label="validation -> 400")
T1, T2, T3 = data(t1)["id"], data(t2)["id"], data(t3)["id"]
assert data(t1)["category"] == "REFUND" and data(t1)["priority"] == "P1", data(t1)
assert data(t2)["category"] == "TECH" and data(t2)["priority"] == "P0", data(t2)
assert data(t3)["category"] == "OTHER" and data(t3)["priority"] == "P2", data(t3)
print("    分类断言通过: REFUND/P1, TECH/P0, OTHER/P2")

print("\n=== 2. LLM 降级路径(挡板故障标记) ===")
_, s1 = call("POST", "/api/tickets", user=1, body={"title": "[SLOW] 退款申请", "content": "慢响应", "customerId": 2001}, expect=201, label="[SLOW] -> timeout -> rules")
assert data(s1)["category"] == "REFUND", data(s1)
_, s2 = call("POST", "/api/tickets", user=1, body={"title": "[BAD_CATEGORY] 账单问题", "content": "越界分类", "customerId": 2002}, expect=201, label="[BAD_CATEGORY] -> OTHER")
assert data(s2)["category"] == "OTHER", data(s2)
_, s3 = call("POST", "/api/tickets", user=1, body={"title": "[BAD_JSON] 登录报错", "content": "非 JSON", "customerId": 2003}, expect=201, label="[BAD_JSON] -> rules")
assert data(s3)["category"] == "TECH", data(s3)
SLOW_ID = data(s1)["id"]

print("\n=== 3. 抢单 / 越权 ===")
call("POST", f"/api/tickets/{T1}/grab", user=6, expect=403, label="agent_c(group2) grab group1 ticket -> 403")
_, g = call("POST", f"/api/tickets/{T1}/grab", user=3, expect=200, label="agent_a grab T1")
assert data(g)["status"] == "ASSIGNED" and data(g)["assigneeId"] == 3
call("POST", f"/api/tickets/{T1}/grab", user=4, expect=409, label="agent_b grab already ASSIGNED -> 409")
call("GET", f"/api/tickets/{T1}", user=4, expect=403, label="agent_b read agent_a ticket -> 403 (水平越权)")
call("GET", f"/api/tickets/{T1}", user=2, expect=200, label="leader_1 read group ticket -> 200")
call("GET", f"/api/tickets/{T1}", user=5, expect=403, label="leader_2 read group1 ticket -> 403")
call("POST", f"/api/tickets/{T1}/assign", user=3, body={"assigneeId": 4}, expect=403, label="agent_a assign -> 403 (垂直越权)")
call("POST", f"/api/tickets/{T1}/assign", user=2, body={"assigneeId": 6}, expect=400, label="leader_1 assign to group2 agent -> 400")
call("POST", f"/api/tickets/{T1}/assign", user=2, body={"assigneeId": 4, "remark": "改派"}, expect=200, label="leader_1 reassign to agent_b")
call("DELETE", f"/api/tickets/{T3}", user=2, expect=403, label="leader delete -> 403")

print("\n=== 4. 状态流转 + 审计 ===")
call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "CLOSED"}, expect=409, label="ASSIGNED->CLOSED illegal -> 409")
call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "PROCESSING", "remark": "开始处理"}, expect=200, label="ASSIGNED->PROCESSING")
call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "WAIT_CONFIRM"}, expect=200, label="PROCESSING->WAIT_CONFIRM")
call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "PROCESSING", "remark": "用户不认可"}, expect=200, label="WAIT_CONFIRM->PROCESSING")
call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "WAIT_CONFIRM"}, expect=200, label="PROCESSING->WAIT_CONFIRM")
_, c = call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "CLOSED"}, expect=200, label="WAIT_CONFIRM->CLOSED")
assert data(c)["closedAt"] is not None
assert data(c)["updatedAt"] != data(c)["createdAt"], "updatedAt 应随更新变化"
call("PUT", f"/api/tickets/{T1}", user=4, body={"title": "x", "content": "y"}, expect=409, label="update CLOSED -> 409")
_, r = call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "PROCESSING", "remark": "7天内重开"}, expect=200, label="CLOSED->PROCESSING reopen")
assert data(r).get("closedAt") is None
call("POST", f"/api/tickets/{T1}/transitions", user=4, body={"target": "PENDING"}, expect=409, label="PROCESSING->PENDING illegal -> 409")
_, a = call("GET", f"/api/tickets/{T1}/audit-logs", user=4, expect=200, label="audit logs T1")
logs = data(a)
print(f"    审计条数={len(logs)}: " + " | ".join(f"{l.get('fromStatus')}->{l['toStatus']}({l['source']})" for l in logs))
assert logs[0].get("fromStatus") is None and logs[0]["source"] == "LLM"
assert all(l["traceId"] for l in logs)

print("\n=== 5. 退回 PENDING(assignee 清空)+ 列表按角色收窄 ===")
call("POST", f"/api/tickets/{T2}/grab", user=3, expect=200, label="agent_a grab T2")
_, back = call("POST", f"/api/tickets/{T2}/transitions", user=3, body={"target": "PENDING", "remark": "退回"}, expect=200, label="ASSIGNED->PENDING 退回")
assert data(back).get("assigneeId") is None, data(back)
_, la = call("GET", "/api/tickets?page=1&size=50", user=3, expect=200, label="agent_a list (own only)")
assert all(rec.get("assigneeId") == 3 for rec in data(la)["records"]), data(la)
_, ll = call("GET", "/api/tickets?page=1&size=50", user=5, expect=200, label="leader_2 list (group2 only)")
assert all(rec["groupId"] == 2 for rec in data(ll)["records"]), data(ll)
_, lad = call("GET", "/api/tickets?status=PENDING&page=1&size=50", user=1, expect=200, label="admin list PENDING")
call("GET", "/api/tickets?page=0", user=1, expect=400, label="page=0 -> 400")

print("\n=== 6. 回复草稿(LLM 第二调用点) ===")
call("POST", f"/api/tickets/{T1}/reply-draft", user=3, expect=403, label="agent_a draft on agent_b ticket -> 403")
_, d1 = call("POST", f"/api/tickets/{T1}/reply-draft", user=4, expect=200, label="agent_b draft (mock)")
assert data(d1)["degraded"] is False and "申请退款" in data(d1)["draft"], data(d1)
_, d2 = call("POST", f"/api/tickets/{SLOW_ID}/reply-draft", user=1, expect=200, label="[SLOW] draft -> degraded template")
assert data(d2)["degraded"] is True and data(d2)["degradeReason"] == "TIMEOUT", data(d2)

print("\n=== 7. 附件:合法 + 三种绕过 ===")
def upload(tid, user, filename, ctype, content, expect, label):
    boundary = "----TicketQaBoundary"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return call("POST", f"/api/tickets/{tid}/attachments", user=user, raw=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, expect=expect, label=label)
PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"\x00" * 100
JPG = bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 100
upload(T1, 4, "photo.png", "image/png", PNG, 201, "png ok")
upload(T1, 4, "note.txt", "text/plain; charset=utf-8", "这是一段中文文本\n".encode("utf-8"), 201, "txt ok")
upload(T1, 4, "shell.php", "application/x-php", b"<?php echo 1; ?>", 415, "php ext -> 415")
upload(T1, 4, "shell.jpg", "image/jpeg", b"<?php echo 1; ?>", 415, "php content as .jpg -> 415 (magic mismatch)")
upload(T1, 4, "photo.jpg", "application/octet-stream", JPG, 415, "octet-stream declared -> 415")
upload(T1, 4, "a.jpg.php", "image/jpeg", JPG, 415, "double ext -> 415")
upload(T1, 4, "big.png", "image/png", PNG + b"\x00" * (5 * 1024 * 1024), 413, "5MB+ -> 413")
upload(T1, 3, "photo.png", "image/png", PNG, 403, "agent_a upload to agent_b ticket -> 403")
_, al = call("GET", f"/api/tickets/{T1}/attachments", user=4, expect=200, label="list attachments")
assert len(data(al)) == 2, data(al)

print("\n=== 8. SLA 手动扫描(此时没有超时单) ===")
call("POST", "/api/admin/sla/scan", user=2, expect=403, label="leader scan -> 403")
call("POST", "/api/admin/sla/scan", user=1, expect=200, label="admin scan")

print("\n=== 9. Prometheus 指标 ===")
req = urllib.request.Request(BASE + "/actuator/prometheus")
with urllib.request.urlopen(req, timeout=10) as r: metrics = r.read().decode("utf-8")
for key in ["llm_fallback_total", "llm_contract_violation_total", "llm_circuit_state", "llm_call_duration_seconds_count",
            "mq_event_published_total", "mq_event_consumed_total", "sla_scan_total", "http_server_requests_seconds_count{"]:
    lines = [l for l in metrics.splitlines() if l.startswith(key)]
    print(f"    {key}: " + (" ; ".join(lines[:4]) if lines else "!!! MISSING"))
    if not lines: FAILS.append("metric " + key)

print("\n=== RESULT ===")
print("FAILS:", FAILS if FAILS else "none")
print("IDS:", {"T1": T1, "T2": T2, "T3": T3, "SLOW": SLOW_ID})
