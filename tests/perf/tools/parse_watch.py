"""把 Arthas watch 的输出(表达式返回 [epochMs, threadName, cost, methodName, sql] 的列表)整理成按线程的时间线。

用法:
    python tools/parse_watch.py results/arthas_watch_jdbc_t20.txt [--getconn results/arthas_watch_getconn_t20.txt] [--ticket 8232]

watch 的表达式在 -s(返回时)求值,所以列表里的 epochMs 是"返回时刻",发出时刻 = 返回时刻 - cost。
输出每个线程:getConnection 等待、SELECT 发出 / 返回、UPDATE 发出 / 返回、INSERT、commit 返回,
以及 SELECT 发出 → commit 返回 的窗口宽度。
"""
import argparse
import re
import sys
from collections import defaultdict

ENTRY = re.compile(r"ts=(\S+ \S+); \[cost=([\d.]+)ms\] result=@ArrayList\[\n((?:\s+@.*\n)+?)\]", re.M)
ITEM = re.compile(r"^\s+@\w+\[(.*)\],$", re.M)


def load(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for m in ENTRY.finditer(text):
        items = ITEM.findall(m.group(3))
        out.append(items)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jdbc")
    ap.add_argument("--getconn")
    ap.add_argument("--ticket", type=int)
    ap.add_argument("--out")
    a = ap.parse_args()
    per = defaultdict(list)
    getconn_inline = defaultdict(list)
    for items in load(a.jdbc):
        if len(items) < 5:
            continue
        end_ms, thread, cost, meth, sql = int(items[0]), items[1], float(items[2]), items[3], items[4]
        if meth == "getConnection":   # 单 watcher 模式:getConnection 也在同一个文件里
            getconn_inline[thread].append((end_ms - cost, end_ms, cost))
            continue
        sql = sql.split(": ", 1)[-1] if "ClientPreparedStatement" in sql else meth.upper()
        kind = meth.upper() if meth in ("commit", "rollback") else sql.split()[0].upper()
        if a.ticket and kind != "COMMIT" and f"id={a.ticket}" not in sql and f"WHERE id={a.ticket}" not in sql and f"VALUES ({a.ticket}," not in sql:
            continue
        # Hikari 生成的子类和父类都被增强时同一次调用会出现两条(内层 cost 略小),按线程+类型+返回时刻去重,保留外层
        dup = [e for e in per[thread] if e[3] == kind and abs(e[1] - end_ms) <= 1 and abs(e[0] - (end_ms - cost)) <= 1.5]
        if dup:
            if cost > dup[0][2]:
                per[thread].remove(dup[0])
            else:
                continue
        per[thread].append((end_ms - cost, end_ms, cost, kind, sql[:70]))
    getconn = defaultdict(list)
    for th, lst in getconn_inline.items():   # 同一次调用外层 getConnection() 和内层 getConnection(long) 各一条,保留 cost 大的
        lst.sort()
        for g in lst:
            if getconn[th] and abs(getconn[th][-1][1] - g[1]) <= 1:
                if g[2] > getconn[th][-1][2]:
                    getconn[th][-1] = g
                continue
            getconn[th].append(g)
    if a.getconn:
        for items in load(a.getconn):
            if len(items) >= 3:
                getconn[items[1]].append((int(items[0]) - float(items[2]), int(items[0]), float(items[2])))
    if not per:
        print("no entries")
        return 1
    base = min(e[0] for evs in per.values() for e in evs)
    lines = [f"基准 t0 = epoch {base:.0f} ms;每行:线程 | 事件 | 发出(+ms) | 返回(+ms) | 耗时 ms | SQL"]
    summary = []
    for thread, evs in sorted(per.items(), key=lambda kv: kv[1][0][0]):
        evs.sort()
        for gc in sorted(getconn.get(thread, [])):
            if base - 200 <= gc[0] <= base + 2000:
                lines.append(f"{thread:<22} | getConnection    | {gc[0]-base:7.1f} | {gc[1]-base:7.1f} | {gc[2]:7.2f} |")
        sel = upd = ins = com = None
        for st, en, cost, kind, sql in evs:
            lines.append(f"{thread:<22} | {kind:<16} | {st-base:7.1f} | {en-base:7.1f} | {cost:7.2f} | {sql}")
            if kind == "SELECT" and sel is None: sel = (st, en)
            if kind == "UPDATE": upd = (st, en)
            if kind == "INSERT": ins = (st, en)
            if kind in ("COMMIT", "ROLLBACK"): com = (st, en)
        lines.append("")
        # 取紧贴这次 SELECT 之前结束的那次 getConnection(同一线程之前可能还处理过 setUp 的创建请求)
        gw = None
        if sel:
            cands = [g for g in getconn.get(thread, []) if g[1] <= sel[0] + 1]
            if cands:
                gw = max(cands, key=lambda g: g[1])[2]
        summary.append((thread, sel, upd, ins, com, gw))
    lines.append("摘要(+ms 相对 t0):线程 | getConnection 等待 | SELECT 发出 | SELECT 返回 | UPDATE 发出 | UPDATE 返回(含行锁等待) | COMMIT 返回 | 窗口 SELECT发出→COMMIT返回")
    for thread, sel, upd, ins, com, gw in sorted(summary, key=lambda s: s[1][0] if s[1] else 1e18):
        if not sel:
            continue
        f = lambda v: f"{v-base:7.1f}" if v is not None else "      -"
        win = f"{com[1]-sel[0]:6.1f}" if com else "     -"
        gws = f"{gw:6.2f}" if gw is not None else "     -"
        lines.append(f"  {thread:<22} | {gws} | {f(sel[0])} | {f(sel[1])} | {f(upd[0]) if upd else '      -'} | {f(upd[1]) if upd else '      -'} | {f(com[1]) if com else '      -'} | {win}  {'UPDATE 执行了' if upd else '(只 SELECT,409)'}")
    text = "\n".join(lines)
    print(text)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
