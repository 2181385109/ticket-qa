"""压测期间每秒抓一次 /actuator/prometheus,把关心的几项写成 CSV;跑完再用 --summarize 看峰值 / 均值。

用法:
    python tools/metrics_sampler.py --out results/m_create_t10.csv --duration 75      # 采样 75 秒
    python tools/metrics_sampler.py --summarize results/m_create_t10.csv             # 汇总
    python tools/metrics_sampler.py --snapshot                                       # 打印一次当前值

关心的指标(都是 Actuator / Micrometer 自带 + 本项目自定义):
    hikaricp_connections_active / pending / idle   DB 连接池:在用 / 排队等连接 / 空闲
    tomcat_threads_busy_threads                     Tomcat 正在处理请求的线程
    jvm_memory_used_bytes{area=heap}                堆已用(各代求和)
    jvm_gc_pause_seconds_count / _sum               GC 次数 / 总停顿秒(累计值,summarize 时取差分)
    process_cpu_usage / system_cpu_usage            JVM 进程 CPU / 整机 CPU(0~1)
    llm_fallback_total / llm_circuit_open_total     LLM 降级 / 熔断累计
    mq_event_published_total / mq_event_publish_failed_total
    http_server_requests_seconds_count              请求累计数(所有 uri 求和)
只抓不判断。
"""
import argparse
import csv
import re
import sys
import time
import urllib.request

URL = "http://localhost:8080/actuator/prometheus"
LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+0-9.eEnaNIif]+)')

WANT = {
    "hikari_active": ("hikaricp_connections_active", None),
    "hikari_pending": ("hikaricp_connections_pending", None),
    "hikari_idle": ("hikaricp_connections_idle", None),
    "tomcat_busy": ("tomcat_threads_busy_threads", None),   # 本项目未开 mbeanregistry,始终 0(见问题清单)
    "jvm_threads": ("jvm_threads_live_threads", None),
    "threads_blocked": ("jvm_threads_states_threads", 'state="blocked"'),
    "threads_runnable": ("jvm_threads_states_threads", 'state="runnable"'),
    "heap_used_mb": ("jvm_memory_used_bytes", 'area="heap"'),
    "gc_count": ("jvm_gc_pause_seconds_count", None),
    "gc_sum_s": ("jvm_gc_pause_seconds_sum", None),
    "gc_max_s": ("jvm_gc_pause_seconds_max", None),
    "proc_cpu": ("process_cpu_usage", None),
    "sys_cpu": ("system_cpu_usage", None),
    "llm_fallback": ("llm_fallback_total", None),
    "llm_circuit_open": ("llm_circuit_open_total", None),
    "llm_circuit_state": ("llm_circuit_state", None),
    "mq_published": ("mq_event_published_total", None),
    "mq_publish_failed": ("mq_event_publish_failed_total", None),
    "mq_consumed": ("mq_event_consumed_total", None),
    "http_count": ("http_server_requests_seconds_count", None),
}


def scrape():
    with urllib.request.urlopen(URL, timeout=5) as r:
        text = r.read().decode()
    acc = {k: 0.0 for k in WANT}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        m = LINE.match(line)
        if not m:
            continue
        name, labels, val = m.group(1), m.group(2) or "", m.group(3)
        for key, (want, lab) in WANT.items():
            if name == want and (lab is None or lab in labels):
                v = float(val)
                acc[key] = max(acc[key], v) if key == "gc_max_s" else acc[key] + v
    acc["heap_used_mb"] = acc["heap_used_mb"] / 1024 / 1024
    return acc


def sample(out, duration, interval):
    keys = ["t", "clock"] + list(WANT)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(keys)
        t0 = time.time()
        while time.time() - t0 < duration:
            try:
                s = scrape()
                row = [round(time.time() - t0, 1), time.strftime("%H:%M:%S")] + [round(s[k], 3) for k in WANT]
            except Exception as e:  # 服务不可达也记一行,故障注入时有用
                row = [round(time.time() - t0, 1), time.strftime("%H:%M:%S")] + [f"ERR:{type(e).__name__}"] + [""] * (len(WANT) - 1)
            w.writerow(row)
            f.flush()
            time.sleep(interval)


def summarize(path):
    rows = [r for r in csv.DictReader(open(path)) if not str(r["hikari_active"]).startswith("ERR")]
    if not rows:
        print("no rows")
        return
    def col(k):
        return [float(r[k]) for r in rows]
    first, last = rows[0], rows[-1]
    print(f"{path}: {len(rows)} samples {first['clock']}..{last['clock']}")
    for k in ["hikari_active", "hikari_pending", "jvm_threads", "threads_blocked", "threads_runnable", "heap_used_mb", "proc_cpu", "sys_cpu"]:
        v = col(k)
        print(f"  {k:16s} max={max(v):8.2f} avg={sum(v)/len(v):8.2f}")
    for k in ["gc_count", "gc_sum_s", "llm_fallback", "llm_circuit_open", "mq_published", "mq_publish_failed", "mq_consumed", "http_count"]:
        print(f"  {k:16s} delta={float(last[k]) - float(first[k]):8.2f}  (first={first[k]} last={last[k]})")
    print(f"  gc_max_s         max={max(col('gc_max_s')):.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--summarize")
    ap.add_argument("--snapshot", action="store_true")
    a = ap.parse_args()
    if a.snapshot:
        for k, v in scrape().items():
            print(f"{k:18s} {v}")
    elif a.summarize:
        summarize(a.summarize)
    elif a.out:
        sample(a.out, a.duration, a.interval)
    else:
        ap.print_help()


if __name__ == "__main__":
    sys.exit(main())
