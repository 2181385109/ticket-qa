"""从服务日志(MyBatis DEBUG)还原一张工单在抢单竞态里每个请求线程的 SQL 顺序与毫秒时间。

用法:
    python tools/race_timeline.py ../../service/logs/ticket-qa-service.log <ticket_id> [--out results/x.txt]

原理:日志行形如
    2026-09-20T18:02:02.045+08:00 DEBUG ... [http-nio-8080-exec-1] c.t.mapper.TicketMapper.selectById : ==>  Preparing: SELECT ...
    ...                                    [http-nio-8080-exec-1] c.t.mapper.TicketMapper.selectById : ==> Parameters: 8216(Long)
    ...                                    [http-nio-8080-exec-1] c.t.mapper.TicketMapper.updateById : ==> Parameters: ..., ASSIGNED(String), ..., 8216(Long)
按线程名归组,只保留 Parameters 里带该 ticket_id 的语句,得到每个线程:SELECT 发出时刻 → 返回 → UPDATE 发出 → 返回 → 审计 INSERT。
文件日志没有 traceId(只有 console pattern 配了 %X{traceId}),所以只能按线程名对齐;同一时间窗内一个线程只处理一个请求,足够用。
"""
import argparse
import re
import sys
from collections import defaultdict

LINE = re.compile(r'^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3})\S* +(\w+) +\d+ --- \[[^\]]*\] \[([^\]]+)\] (\S+)\s*: (.*)$')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("ticket_id", type=int)
    ap.add_argument("--out")
    a = ap.parse_args()
    tid = f"{a.ticket_id}(Long)"
    # 每个线程按"请求段"归组:一段从 SELECT 这张单开始,到 审计 INSERT 返回 / 409 拒绝 结束;
    # 之后同一线程再 SELECT 这张单(比如 tearDown 的 GET)就是新的一段,只用于区分,不进摘要。
    segments = {}                    # (thread, seq) -> [(ts, mapper, phase, text)]
    state = {}                       # thread -> (seq, status)  status: selected / updated / done
    pending_prepare = {}             # thread -> (ts, mapper, sql)  上一条 Preparing,等它的 Parameters 判断是不是这张单
    def cur(thread):
        seq, _ = state.get(thread, (0, "done"))
        return segments.setdefault((thread, seq), [])
    with open(a.log, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LINE.match(line.rstrip())
            if not m:
                continue
            ts, level, thread, logger, msg = m.groups()
            if not thread.startswith("http-nio"):
                continue
            if msg.startswith("==>  Preparing:"):
                pending_prepare[thread] = (ts, logger.split(".")[-1], msg[len("==>  Preparing: "):][:60])
            elif msg.startswith("==> Parameters:"):
                prep = pending_prepare.pop(thread, None)
                if not prep or tid not in msg:
                    continue
                mapper = prep[1]
                seq, st = state.get(thread, (0, "done"))
                if mapper == "selectById" and st == "done":
                    seq += 1
                    state[thread] = (seq, "selected")
                elif mapper == "updateById" and st == "selected":
                    state[thread] = (seq, "updated")
                elif st == "done":
                    continue
                segs = cur(thread)
                segs.append((prep[0], mapper, "SEND", prep[2]))
                segs.append((ts, mapper, "PARAMS", msg[len("==> Parameters: "):][:120]))
                segs.append(("?", mapper, "WAIT_RESULT", ""))
            elif msg.startswith("<=="):
                segs = segments.get((thread, state.get(thread, (0, "done"))[0]))
                if segs and segs[-1][2] == "WAIT_RESULT":
                    segs[-1] = (ts, segs[-1][1], "RESULT", msg.strip())
                    if segs[-1][1] == "insert" and state[thread][1] == "updated":
                        state[thread] = (state[thread][0], "done")
            elif ("IllegalTransition" in msg or "只能抢" in msg) and state.get(thread, (0, "done"))[1] == "selected":
                cur(thread).append((ts, "-", "REJECT", msg[:100]))
                state[thread] = (state[thread][0], "done")
    per_thread = {f"{th}#{seq}": evs for (th, seq), evs in segments.items() if evs}
    out = []
    def hms_ms(ts):
        h, mi, s = ts[11:].split(":")
        return (int(h) * 3600 + int(mi) * 60 + float(s)) * 1000
    all_ts = [e[0] for evs in per_thread.values() for e in evs if e[0] != "?"]
    if not all_ts:
        print("no events for ticket", a.ticket_id)
        return 1
    base = min(hms_ms(t) for t in all_ts)
    out.append(f"ticket_id={a.ticket_id}  线程数={len(per_thread)}  t0={min(all_ts)}  (+ms 相对 t0)")
    out.append(f"{'线程':<22} {'+ms':>6}  {'mapper':<12} {'阶段':<11} 内容")
    summary = []
    for thread, evs in sorted(per_thread.items(), key=lambda kv: min(hms_ms(e[0]) for e in kv[1] if e[0] != "?")):
        sel_send = sel_ret = upd_send = upd_ret = None
        for ts, mapper, phase, text in evs:
            rel = f"{hms_ms(ts) - base:6.0f}" if ts != "?" else "     ?"
            out.append(f"{thread:<22} {rel}  {mapper:<12} {phase:<11} {text}")
            if mapper == "selectById" and phase == "SEND": sel_send = hms_ms(ts)
            if mapper == "selectById" and phase == "RESULT": sel_ret = hms_ms(ts)
            if mapper == "updateById" and phase == "SEND": upd_send = hms_ms(ts)
            if mapper == "updateById" and phase == "RESULT": upd_ret = hms_ms(ts)
        if sel_send is not None and (upd_send is not None or any(e[2] == "REJECT" for e in evs)):
            summary.append((thread, sel_send - base, sel_ret - base if sel_ret else None,
                            upd_send - base if upd_send else None, upd_ret - base if upd_ret else None))
        out.append("")
    out.append("每线程摘要(+ms):SELECT 发出 / SELECT 返回 / UPDATE 发出 / UPDATE 返回 / SELECT返回→UPDATE返回 的窗口")
    for th, ss, sr, us, ur in summary:
        win = f"{ur - sr:.0f}" if (ur is not None and sr is not None) else "-"
        out.append(f"  {th:<22} {ss:6.0f} {sr if sr is None else f'{sr:6.0f}'} {us if us is None else f'{us:6.0f}'} {ur if ur is None else f'{ur:6.0f}'}   window={win} ms   {'UPDATE 执行了' if us is not None else '被 409 拦下(没有 UPDATE)'}")
    text = "\n".join(out)
    print(text)
    if a.out:
        open(a.out, "w", encoding="utf-8").write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
