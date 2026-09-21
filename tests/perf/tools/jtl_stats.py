"""把 JMeter 的 CSV 结果(-l 生成的 summary jtl)汇总成一行指标:样本数、时长、QPS、P50/P95/P99、错误率。

用法:
    python tools/jtl_stats.py results/create_t10.jtl            # 全部采样
    python tools/jtl_stats.py results/grab_t20.jtl --label grab  # 只统计 label 以 grab 开头的采样
    python tools/jtl_stats.py results/*.jtl --md                 # 多个文件,输出 markdown 表

只做统计,不做判断。分位数用最近秩法(与 JMeter Aggregate Report 一致:nearest-rank)。
"""
import argparse
import csv
import glob
import math
import os
import sys
from collections import Counter


def percentile(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    k = max(1, math.ceil(p / 100 * len(sorted_vals)))
    return sorted_vals[k - 1]


def stats(path, label_prefix=None):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if label_prefix and not r["label"].startswith(label_prefix):
                continue
            rows.append(r)
    if not rows:
        return None
    elapsed = sorted(int(r["elapsed"]) for r in rows)
    ts = [int(r["timeStamp"]) for r in rows]
    ends = [int(r["timeStamp"]) + int(r["elapsed"]) for r in rows]
    wall_ms = max(ends) - min(ts)
    errors = sum(1 for r in rows if r["success"] != "true")
    codes = Counter(r["responseCode"] for r in rows)
    labels = Counter(r["label"] for r in rows)
    return {
        "file": os.path.basename(path),
        "samples": len(rows),
        "wall_s": wall_ms / 1000,
        "qps": len(rows) / (wall_ms / 1000) if wall_ms else float("nan"),
        "avg": sum(elapsed) / len(elapsed),
        "p50": percentile(elapsed, 50),
        "p95": percentile(elapsed, 95),
        "p99": percentile(elapsed, 99),
        "max": elapsed[-1],
        "min": elapsed[0],
        "errors": errors,
        "err_rate": errors / len(rows),
        "codes": dict(codes),
        "labels": dict(labels),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--label", help="只统计 label 以此前缀开头的采样")
    ap.add_argument("--md", action="store_true", help="输出 markdown 表格")
    ap.add_argument("--labels", action="store_true", help="附带每个 label 的次数分布")
    a = ap.parse_args()
    paths = [p for pat in a.files for p in sorted(glob.glob(pat))]
    results = [s for s in (stats(p, a.label) for p in paths) if s]
    if a.md:
        print("| 文件 | 样本 | 时长 s | QPS | 平均 ms | P50 | P95 | P99 | Max | 错误 | 错误率 | HTTP 码分布 |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in results:
            print(f"| {s['file']} | {s['samples']} | {s['wall_s']:.1f} | {s['qps']:.1f} | {s['avg']:.1f} | {s['p50']} | {s['p95']} | {s['p99']} | {s['max']} | {s['errors']} | {s['err_rate']:.2%} | {s['codes']} |")
    else:
        for s in results:
            print(f"{s['file']}: samples={s['samples']} wall={s['wall_s']:.1f}s qps={s['qps']:.1f} avg={s['avg']:.1f} "
                  f"p50={s['p50']} p95={s['p95']} p99={s['p99']} max={s['max']} errors={s['errors']} ({s['err_rate']:.2%}) codes={s['codes']}")
    if a.labels:
        for s in results:
            print(f"\n{s['file']} label 分布:")
            for k, v in sorted(s["labels"].items(), key=lambda kv: -kv[1]):
                print(f"  {v:6d}  {k}")


if __name__ == "__main__":
    sys.exit(main())
