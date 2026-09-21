"""故障注入用的探针:一次调用把"接口层 / 健康端点 / 指标 / 库"四个视角各采一遍,带时间戳追加到日志文件。

用法:
    python tools/fault_probe.py --log results/fault_redis.log --label "基线"
    python tools/fault_probe.py --log results/fault_redis.log --label "注入中 #1" --title "[SLOW] 退款"   # 指定标题

每次做的事(顺序固定,便于前后对照):
    1. GET  /actuator/health                        → HTTP 码 + 各组件状态
    2. GET  /api/agents/me (X-User-Id: 3)           → 鉴权路径(走 Redis 缓存)的耗时
    3. POST /api/tickets                            → 创建(LLM 分类 + 落库 + 审计 + MQ)的耗时、code、category/priority、traceId
    4. POST /api/tickets/{id}/grab (X-User-Id: 3)   → 状态变更(落库 + 审计 + 2 条 MQ)的耗时、code、traceId
    5. /actuator/prometheus 里的 mq_* / llm_* / sla_* 计数
    6. 库:这张工单的 llm_call_log(degraded / degrade_reason / latency_ms)、审计行数、mq_message_dedup 里的行数
只记录不判断;"预期 vs 实际"写在 findings 里。
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8080"
LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eEnaNIif]+)')


def call(method, path, body=None, user="1", timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-User-Id": user, "Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, text = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read().decode()
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", (time.perf_counter() - t0) * 1000
    return code, text, (time.perf_counter() - t0) * 1000


def metrics():
    want = ["mq_event_published_total", "mq_event_publish_failed_total", "mq_event_consumed_total",
            "llm_fallback_total", "llm_circuit_open_total", "llm_circuit_state", "sla_scan_lock_unavailable_total", "sla_scan_total"]
    acc = {k: 0.0 for k in want}
    try:
        with urllib.request.urlopen(BASE + "/actuator/prometheus", timeout=10) as r:
            for line in r.read().decode().splitlines():
                m = LINE.match(line)
                if m and m.group(1) in acc:
                    acc[m.group(1)] += float(m.group(3))
    except Exception as e:
        return {"_error": str(e)}
    return acc


def db_rows(ticket_id):
    try:
        import pymysql
        c = pymysql.connect(host="127.0.0.1", user="ticketqa", password="ticketqa123", database="ticket_qa", cursorclass=pymysql.cursors.DictCursor)
        with c.cursor() as cur:
            cur.execute("SELECT scene, request_model, response_model, latency_ms, degraded, degrade_reason, raw_category, final_category FROM llm_call_log WHERE ticket_id=%s ORDER BY id", (ticket_id,))
            llm = cur.fetchall()
            cur.execute("SELECT COUNT(*) n FROM ticket_audit_log WHERE ticket_id=%s", (ticket_id,))
            audit = cur.fetchone()["n"]
            cur.execute("SELECT status, assignee_id FROM ticket WHERE id=%s", (ticket_id,))
            t = cur.fetchone()
        c.close()
        return llm, audit, t
    except Exception as e:
        return [{"_error": str(e)}], None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--title", default="故障注入探针 退款")
    ap.add_argument("--wait-dedup", type=float, default=1.5, help="查去重表前等消费者多久(秒)")
    a = ap.parse_args()
    out = [f"===== {time.strftime('%H:%M:%S')}  {a.label}"]
    code, text, ms = call("GET", "/actuator/health", user="1")
    comps = ""
    try:
        j = json.loads(text)
        comps = " ".join(f"{k}={v.get('status')}" for k, v in j.get("components", {}).items() if k in ("db", "redis", "rabbit", "ping"))
        comps = f"status={j.get('status')} {comps}"
    except Exception:
        comps = text[:120]
    out.append(f"health   HTTP {code} {ms:7.1f} ms  {comps}")
    code, text, ms = call("GET", "/api/agents/me", user="3")
    out.append(f"me       HTTP {code} {ms:7.1f} ms  {text[:90]}")
    code, text, ms = call("POST", "/api/tickets", {"title": a.title, "content": "订单重复扣款,请退款(故障注入探针)", "customerId": 4242, "groupId": 1})
    tid = None
    try:
        j = json.loads(text)
        tid = j.get("data", {}).get("id")
        out.append(f"create   HTTP {code} {ms:7.1f} ms  code={j.get('code')} id={tid} category={j.get('data', {}).get('category')} priority={j.get('data', {}).get('priority')} traceId={j.get('traceId')}")
    except Exception:
        out.append(f"create   HTTP {code} {ms:7.1f} ms  {text[:160]}")
    if tid:
        code, text, ms = call("POST", f"/api/tickets/{tid}/grab", user="3")
        try:
            j = json.loads(text)
            out.append(f"grab     HTTP {code} {ms:7.1f} ms  code={j.get('code')} status={j.get('data', {}).get('status')} assignee={j.get('data', {}).get('assigneeId')} traceId={j.get('traceId')}")
        except Exception:
            out.append(f"grab     HTTP {code} {ms:7.1f} ms  {text[:160]}")
    m = metrics()
    out.append("metrics  " + " ".join(f"{k.replace('_total', '')}={v:.0f}" if isinstance(v, float) else f"{k}={v}" for k, v in m.items()))
    if tid:
        time.sleep(a.wait_dedup)
        llm, audit, t = db_rows(tid)
        out.append(f"db       ticket={t} audit_rows={audit} llm_call_log={llm}")
        try:
            import pymysql
            c = pymysql.connect(host="127.0.0.1", user="ticketqa", password="ticketqa123", database="ticket_qa")
            with c.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM mq_message_dedup WHERE ticket_id=%s", (tid,))
                out.append(f"db       mq_message_dedup rows for ticket {tid} = {cur.fetchone()[0]} (创建 1 + 抢单 2 = 3 为全部消费)")
            c.close()
        except Exception as e:
            out.append(f"db       mq_message_dedup query failed: {e}")
    text = "\n".join(out)
    print(text)
    with open(a.log, "a", encoding="utf-8") as f:
        f.write(text + "\n\n")


if __name__ == "__main__":
    main()
