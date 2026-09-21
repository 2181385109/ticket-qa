"""把 run_load.sh 的一轮产物转成质量数据平台的导入格式(POST /api/perf-runs),可选直接 POST。

用法(在 tests/perf 下):
    python tools/to_platform.py fix_grab_t50                       # 打印 JSON
    python tools/to_platform.py fix_grab_t50 --post                # POST 到 http://localhost:8081
    python tools/to_platform.py fix_grab_t50 --post --baseline     # 同时设为该 scenario+threads 的基线
    python tools/to_platform.py fix_create_t50 --scenario create --threads 50 --post
    python tools/to_platform.py fix_read_t10 --post --url http://localhost:8081

读什么:
    results/<tag>.jtl                 JMeter 汇总(qps / 分位数 / 错误率,复用 jtl_stats.py 的算法)
    results/<tag>_env_before.json     压测前环境状态(env_state.py --json)——必带,平台拒收没有环境的轮次(KI-010)
    results/<tag>_report.md           从第一行取线程 / 持续时长 / 执行时间(没有就用命令行给的)
scenario / threads 默认从 tag 里猜(<prefix>_<scenario>_t<threads>),猜不出就必须显式给。
"""
import argparse
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from jtl_stats import stats  # noqa: E402


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def guess(tag):
    m = re.search(r"(?:^|_)(create|grab|read|grab_race)_t(\d+)", tag)
    return (m.group(1), int(m.group(2))) if m else (None, None)


def report_header(path):
    """report.md 第 3 行形如:脚本 `x.jmx`,线程 50,ramp-up 10s,持续 20s,额外参数 ``,执行时间 2026-09-21 01:54:41"""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        text = f.read(2000)
    out = {}
    m = re.search(r"线程 (\d+)", text)
    if m:
        out["threads"] = int(m.group(1))
    m = re.search(r"持续 (\d+)s", text)
    if m:
        out["duration_s"] = int(m.group(1))
    m = re.search(r"执行时间 (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    if m:
        out["executed_at"] = m.group(1)
    return out


def build(tag, scenario, threads, results_dir, note):
    st = stats(os.path.join(results_dir, f"{tag}.jtl"))
    if st is None:
        raise SystemExit(f"{tag}.jtl 没有采样")
    env = load_json(os.path.join(results_dir, f"{tag}_env_before.json"))
    hdr = report_header(os.path.join(results_dir, f"{tag}_report.md"))
    s, t = guess(tag)
    scenario = scenario or s
    threads = threads or hdr.get("threads") or t
    if not scenario or not threads:
        raise SystemExit("无法从 tag 推断 scenario / threads,请用 --scenario / --threads 显式指定")
    return {
        "tag": tag,
        "scenario": scenario,
        "threads": int(threads),
        "durationS": hdr.get("duration_s", int(round(st["wall_s"]))),
        "samples": st["samples"],
        "qps": round(st["qps"], 2),
        "avgMs": round(st["avg"], 2),
        "p50Ms": int(st["p50"]),
        "p95Ms": int(st["p95"]),
        "p99Ms": int(st["p99"]),
        "maxMs": int(st["max"]),
        "errorRate": round(st["err_rate"] * 100, 3),
        "commitSha": env.get("git"),
        "executedAt": hdr.get("executed_at") or env.get("time"),
        "env": env,
        "note": note,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag")
    ap.add_argument("--scenario")
    ap.add_argument("--threads", type=int)
    ap.add_argument("--results", default="results")
    ap.add_argument("--note", default="")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--url", default=os.environ.get("PLATFORM_URL", "http://localhost:8081"))
    args = ap.parse_args()

    payload = build(args.tag, args.scenario, args.threads, args.results, args.note)
    if args.baseline:
        payload["baseline"] = True
    body = json.dumps(payload, ensure_ascii=False, indent=1)
    if not args.post:
        print(body)
        return 0
    req = urllib.request.Request(f"{args.url}/api/perf-runs", data=body.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read().decode("utf-8"))
    print(f"{args.tag}: HTTP {r.status} code={resp.get('code')} id={resp.get('data', {}).get('id')} baseline={resp.get('data', {}).get('baseline')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
