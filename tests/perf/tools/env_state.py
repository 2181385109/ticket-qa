"""压测前后必须落盘的环境状态——没有这一段,压测数字不可复现(见 findings「同一并发不同成功数」)。

用法:
    python tools/env_state.py                      # 打印 markdown 表
    python tools/env_state.py --out results/x_env_before.md --label "create t50 之前"
    python tools/env_state.py --json               # 机器可读

采什么、为什么:
    HikariCP total/idle/active/pending   抢单成功数 = 池内现有连接数 + 1;池会随 idle-timeout 收缩,所以每轮前必须记
    JVM 堆已用 / GC 次数 / GC 总停顿      排除 GC 干扰;GC 计数是累计值,前后两份相减即本轮次数
    SLA 后台任务                          待升级积压(status PENDING/ASSIGNED 且 sla_deadline<=now)>0 意味着调度器每 30 s 在后台写库
    库里工单 / 审计 / LLM 日志行数        数据量影响索引与 buffer pool;也说明"这轮是在多脏的库上跑的"
    MySQL 持久化与日志配置                innodb_flush_log_at_trx_commit / sync_binlog 决定 COMMIT 的 fsync 成本;slow log 开着会拖慢
    Tomcat / 线程                         jvm_threads_live;Tomcat 线程池指标本项目没暴露,只能记 JVM 线程数
    LLM 熔断状态 / MQ 队列积压            故障注入前后对照
数据来源:/actuator/prometheus(Hikari 值来自同一个 HikariPoolMXBean,与 Arthas vmtool 读到的一致)、MySQL 直连、RabbitMQ 管理 API。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from base64 import b64encode

PROM = "http://localhost:8080/actuator/prometheus"
RABBIT = "http://localhost:15672/api/queues"
LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eEnaNIif]+)')


def prom():
    vals = {}
    try:
        with urllib.request.urlopen(PROM, timeout=5) as r:
            for line in r.read().decode().splitlines():
                m = LINE.match(line)
                if m:
                    vals.setdefault(m.group(1), []).append((m.group(2) or "", float(m.group(3))))
    except Exception as e:
        vals["_error"] = str(e)
    return vals


def pv(vals, name, label=None, agg="sum"):
    xs = [v for lab, v in vals.get(name, []) if label is None or label in lab]
    if not xs:
        return None
    return max(xs) if agg == "max" else sum(xs)


def mysql_state():
    import pymysql
    c = pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"), port=int(os.getenv("MYSQL_PORT", "3306")),
                        user=os.getenv("MYSQL_USER", "ticketqa"), password=os.getenv("MYSQL_PASSWORD", "ticketqa123"),
                        database=os.getenv("MYSQL_DATABASE", "ticket_qa"))
    out = {}
    with c.cursor() as cur:
        for k, sql in [
            ("ticket_rows", "SELECT COUNT(*) FROM ticket"),
            ("ticket_by_status", "SELECT GROUP_CONCAT(CONCAT(status,'=',n) ORDER BY status) FROM (SELECT status, COUNT(*) n FROM ticket GROUP BY status) t"),
            ("audit_rows", "SELECT COUNT(*) FROM ticket_audit_log"),
            ("llm_call_log_rows", "SELECT COUNT(*) FROM llm_call_log"),
            ("mq_dedup_rows", "SELECT COUNT(*) FROM mq_message_dedup"),
            ("sla_backlog", "SELECT COUNT(*) FROM ticket WHERE status IN ('PENDING','ASSIGNED') AND escalated_at IS NULL AND sla_deadline <= NOW(3)"),
            ("sla_next_due_in_min", "SELECT ROUND(TIMESTAMPDIFF(SECOND, NOW(3), MIN(sla_deadline))/60,1) FROM ticket WHERE status IN ('PENDING','ASSIGNED') AND escalated_at IS NULL AND sla_deadline > NOW(3)"),
            ("mysql_threads_connected", "SELECT VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME='Threads_connected'"),
        ]:
            cur.execute(sql)
            out[k] = cur.fetchone()[0]
        cur.execute("SHOW GLOBAL VARIABLES WHERE Variable_name IN ('innodb_flush_log_at_trx_commit','sync_binlog','slow_query_log','long_query_time','log_output','transaction_isolation','innodb_lock_wait_timeout','innodb_buffer_pool_size','max_connections')")
        out["mysql_vars"] = {k: v for k, v in cur.fetchall()}
    c.close()
    return out


def rabbit_state():
    try:
        req = urllib.request.Request(RABBIT, headers={"Authorization": "Basic " + b64encode(b"ticketqa:rabbit123").decode()})
        with urllib.request.urlopen(req, timeout=5) as r:
            qs = json.load(r)
        return {q["name"]: q.get("messages", 0) for q in qs if q["name"].startswith("q.")}
    except Exception as e:
        return {"_error": str(e)}


def collect():
    v = prom()
    s = {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "git": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "hikari": {
            "total": pv(v, "hikaricp_connections"), "idle": pv(v, "hikaricp_connections_idle"),
            "active": pv(v, "hikaricp_connections_active"), "pending": pv(v, "hikaricp_connections_pending"),
            "max": pv(v, "hikaricp_connections_max"), "acquire_max_s": pv(v, "hikaricp_connections_acquire_seconds_max", agg="max"),
            "timeout_total": pv(v, "hikaricp_connections_timeout_total"),
        },
        "jvm": {
            "heap_used_mb": round((pv(v, "jvm_memory_used_bytes", 'area="heap"') or 0) / 1048576, 1),
            "heap_max_mb": round((pv(v, "jvm_memory_max_bytes", 'id="G1 Old Gen"') or 0) / 1048576, 1),
            "gc_count": pv(v, "jvm_gc_pause_seconds_count"), "gc_sum_s": round(pv(v, "jvm_gc_pause_seconds_sum") or 0, 3),
            "gc_max_s": pv(v, "jvm_gc_pause_seconds_max", agg="max"),
            "threads_live": pv(v, "jvm_threads_live_threads"), "threads_blocked": pv(v, "jvm_threads_states_threads", 'state="blocked"'),
            "uptime_s": pv(v, "process_uptime_seconds"), "cpu_process": pv(v, "process_cpu_usage"), "cpu_system": pv(v, "system_cpu_usage"),
        },
        "sla": {"scan_total": pv(v, "sla_scan_total"), "escalated_total": pv(v, "sla_escalated_total")},
        "llm": {"circuit_state": pv(v, "llm_circuit_state"), "fallback_total": pv(v, "llm_fallback_total") or 0,
                "circuit_open_total": pv(v, "llm_circuit_open_total") or 0},
        "mq": {"published": pv(v, "mq_event_published_total"), "consumed": pv(v, "mq_event_consumed_total"),
               "publish_failed": pv(v, "mq_event_publish_failed_total"), "queues": rabbit_state()},
        "http_requests_total": pv(v, "http_server_requests_seconds_count"),
    }
    try:
        s["mysql"] = mysql_state()
    except Exception as e:
        s["mysql"] = {"_error": str(e)}
    return s


def markdown(s, label=None):
    h, j, m = s["hikari"], s["jvm"], s.get("mysql", {})
    mv = m.get("mysql_vars", {})
    rows = [
        ("采集时间", s["time"] + (f"({label})" if label else "")),
        ("服务版本", f"git {s['git']},JVM uptime {int(j['uptime_s'] or 0)} s"),
        ("HikariCP total/idle/active/pending(max)", f"{h['total']:.0f}/{h['idle']:.0f}/{h['active']:.0f}/{h['pending']:.0f} ({h['max']:.0f});acquire_max {h['acquire_max_s']}s,timeout_total {h['timeout_total']:.0f}" if h["total"] is not None else "服务不可达"),
        ("JVM 堆已用 / 上限", f"{j['heap_used_mb']} / {j['heap_max_mb']} MB"),
        ("GC 累计次数 / 累计停顿 / 单次最大", f"{j['gc_count']:.0f} 次 / {j['gc_sum_s']} s / {j['gc_max_s']} s" if j["gc_count"] is not None else "-"),
        ("JVM 线程(live / blocked)", f"{j['threads_live']} / {j['threads_blocked']}"),
        ("SLA 后台任务", f"扫描累计 {s['sla']['scan_total']} 轮,升级累计 {s['sla']['escalated_total']};库内待升级积压 {m.get('sla_backlog')} 张,下一批到期 {m.get('sla_next_due_in_min')} 分钟后"),
        ("库内行数 ticket / audit / llm_call_log / mq_dedup", f"{m.get('ticket_rows')} / {m.get('audit_rows')} / {m.get('llm_call_log_rows')} / {m.get('mq_dedup_rows')};按状态 {m.get('ticket_by_status')}"),
        ("MySQL 持久化配置", f"innodb_flush_log_at_trx_commit={mv.get('innodb_flush_log_at_trx_commit')} sync_binlog={mv.get('sync_binlog')} isolation={mv.get('transaction_isolation')} lock_wait_timeout={mv.get('innodb_lock_wait_timeout')} buffer_pool={mv.get('innodb_buffer_pool_size')} max_connections={mv.get('max_connections')} threads_connected={m.get('mysql_threads_connected')}"),
        ("MySQL 慢日志", f"slow_query_log={mv.get('slow_query_log')} long_query_time={mv.get('long_query_time')} log_output={mv.get('log_output')}"),
        ("LLM 熔断 / 降级累计 / 熔断累计", f"state={s['llm']['circuit_state']} fallback={s['llm']['fallback_total']:.0f} open={s['llm']['circuit_open_total']:.0f}"),
        ("MQ 发布 / 消费 / 发布失败;队列积压", f"{s['mq']['published']} / {s['mq']['consumed']} / {s['mq']['publish_failed']};{s['mq']['queues']}"),
        ("HTTP 请求累计", f"{s['http_requests_total']}"),
    ]
    lines = ["| 环境状态 | 值 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--label")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    s = collect()
    text = json.dumps(s, ensure_ascii=False, indent=1, default=str) if a.json else markdown(s, a.label)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        with open(a.out.rsplit(".", 1)[0] + ".json", "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
