"""
混合回放(v2 评估,作者 2026-09-27 决定;取代 2026-09-26 纯回放在请求验证处停下后的四个选项)。

问题:纯回放(llmsec/replay.py)要求 v2 发给模型的请求与 v1 逐字节一致,实测 538 个里 25 个草稿请求不一致——
v1 的交叉校验在建单时把 5 张工单的分类改成了规则结果,v2 不再改,而草稿提示词带着工单分类(`分类:<工单分类>`),
于是这 5 张单后续 5 轮的草稿请求变了。v1 录到的模型输出对这 25 个请求不成立。

做法:服务(v2)以真实模式启动,LLM_BASE_URL 指向本模块的混合代理。代理在**请求到达时**逐字节比对它与 v1 同一任务录到的请求
(与 replay.request_diffs 同一判据):
  - 一致 → 直接返回 v1 录到的响应(复用 v1 的采样,不发真实请求);
  - 不一致且该任务在预期的重采样集合里 → 原样转发到真实上游(重新采样,计入预算);
  - 不一致但不在预期集合里 → 拒绝(502)并停止整次运行——说明 v2 的输入变化超出了已知的 25 个,混合回放的前提不成立。
预期集合 = 纯回放运行里请求不一致的任务(由 v1 与纯回放运行两个目录离线重算,写进 meta)。所以真实调用最多 25 次。

跑完后 check() 离线重算:每个回放任务的请求与 v1 逐字节一致、拿到的输出与 v1 逐字节相同;重采样任务恰好是预期集合、上游 200。
resample_compare.md 把 25 个重采样请求与它们的 v1 版本逐条并排。

与纯回放相比,方法上多了一个代价:一份报告里混着两个时段的采样(v1 的 513 条 + 本次的 25 条)。时段差异的依据见 METHOD_NOTE。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from . import judge as J
from . import replay as RP
from . import review as RV
from .dataset import Dataset
from .proxy import RecordingProxy, request_view
from .runner import Budget, StopRun, Task

RERUN_COMPARE = "tests/llm_security/reports/phase1-rerun-attacks-20260926T083123Z/rerun_compare.md"
METHOD_NOTE = ("混合回放:v2 发给模型的请求与 v1 同一任务逐字节一致的,复用 v1 录制的模型输出(v1 的采样);"
               "不一致的(草稿提示词里的工单分类行变了)在 v2 服务上用真实模型重新采样,每个请求一次调用。"
               "一致与否在请求到达代理时逐字节判定,跑完后离线复核(hybrid_check.md)。"
               "两段采样来自不同时段;时段差异可以忽略的依据是基线复跑:同一份防御前代码在相隔约 22 小时的两个时段"
               "(2026-09-25 10:21 UTC 与 2026-09-26 08:31 UTC)跑同一批攻击样本,四类攻击按样本的成功数完全相同、成功的是同一批样本,"
               f"按运行只有 C 类差 1 次(`{RERUN_COMPARE}`)。")
ORIGIN_REPLAY, ORIGIN_RESAMPLE, ORIGIN_BLOCKED = "replay", "resample", "blocked"
ORIGIN_NAMES = {ORIGIN_REPLAY: "回放 v1 输出", ORIGIN_RESAMPLE: "重新采样"}


# ---------------------------------------------------------------------- 运行时:代理 / 执行器 / 预算

class HybridProxy(RecordingProxy):
    """source:任务 key → v1 录到的那次上游调用;resample_keys:允许重新采样的任务。current_key 由 HybridExecutor 在每次接口调用前设置"""

    def __init__(self, upstream_base: str, source: dict[str, dict[str, Any]], resample_keys: set[str], **kw):
        super().__init__(upstream_base, **kw)
        self.source, self.resample_keys = source, set(resample_keys)
        self.current_key: str | None = None
        self.forwarded = 0
        self._count_lock = threading.Lock()

    def respond(self, method, path, body, headers):
        key = self.current_key
        up = self.source.get(key or "")
        if up is None:
            return self._blocked(f"源运行里没有任务 {key} 的上游调用")
        diffs = RP.request_diffs(up.get("request") or {}, request_view(body))
        if not diffs:
            resp = json.dumps(RP.response_body(key, up), ensure_ascii=False).encode("utf-8")
            return 200, resp, "application/json; charset=utf-8", None, {"hybrid": ORIGIN_REPLAY}
        if key not in self.resample_keys:
            return self._blocked(f"{key} 的请求与 v1 不一致,但不在预期的重采样集合里:" + "; ".join(d["field"] for d in diffs))
        with self._count_lock:
            self.forwarded += 1
        status, resp, ctype, error, _ = super().respond(method, path, body, headers)
        return status, resp, ctype, error, {"hybrid": ORIGIN_RESAMPLE}

    @staticmethod
    def _blocked(why: str):
        body = json.dumps({"error": {"message": f"hybrid proxy: {why}"}}, ensure_ascii=False).encode("utf-8")
        return 502, body, "application/json; charset=utf-8", None, {"hybrid": ORIGIN_BLOCKED, "hybrid_reason": why}


class HybridExecutor:
    """包一层 LiveExecutor:告诉代理当前是哪个任务;代理拒绝过的任务直接停止整次运行(不落盘)"""

    def __init__(self, inner, proxy: HybridProxy):
        self.inner, self.proxy = inner, proxy

    def __call__(self, task: Task, sample: dict[str, Any], ticket_id: int | None) -> dict[str, Any]:
        self.proxy.current_key = task.key
        try:
            rec = self.inner(task, sample, ticket_id)
        finally:
            self.proxy.current_key = None
        blocked = [u for u in rec.get("upstream") or [] if u.get("hybrid") == ORIGIN_BLOCKED]
        if blocked:
            raise StopRun(f"混合回放前提不成立:{blocked[0].get('hybrid_reason')}")
        return rec


class HybridBudget:
    """只把真正转发到上游的调用计入预算(回放的不计)。每次调用前按 1 次检查,保守"""

    def __init__(self, real: Budget, proxy: HybridProxy):
        self.real, self.proxy, self._counted = real, proxy, 0

    @property
    def total(self) -> int:
        return self.real.total

    @property
    def limit(self) -> int:
        return self.real.limit

    def check(self, upcoming: int = 1) -> None:
        self.real.check(1)

    def add(self, run: str, n: int) -> None:
        delta = self.proxy.forwarded - self._counted
        self._counted = self.proxy.forwarded
        self.real.add(run, delta)


# ---------------------------------------------------------------------- 预期集合与验证(离线、确定性)

def expected_resample(v1_records: list[dict[str, Any]], replay_records: list[dict[str, Any]], keys: list[str]) -> list[str]:
    """纯回放运行里请求与 v1 不一致的任务 = 需要重新采样的任务"""
    return sorted({d["key"] for d in RP.compare_requests(v1_records, replay_records, keys)})


def _origin(rec: dict[str, Any]) -> str | None:
    ups = rec.get("upstream") or []
    return ups[0].get("hybrid") if len(ups) == 1 else None


def check(v1_records: list[dict[str, Any]], hy_records: list[dict[str, Any]], keys: list[str],
          expected: list[str]) -> dict[str, Any]:
    src, hy = {r["key"]: r for r in v1_records}, {r["key"]: r for r in hy_records}
    problems: list[str] = []
    replayed, resampled = [], []
    for key in keys:
        r = hy.get(key)
        ups = (r or {}).get("upstream") or []
        if r is None or len(ups) != 1:
            problems.append(f"{key}: 混合运行里没有这条记录,或上游调用不是恰好 1 次")
            continue
        a, b = src[key]["upstream"][0], ups[0]
        origin = b.get("hybrid")
        if b.get("status") != 200:
            problems.append(f"{key}: 上游状态 {b.get('status')}")
        diffs = RP.request_diffs(a.get("request") or {}, b.get("request") or {})
        if origin == ORIGIN_REPLAY:
            replayed.append(key)
            if diffs:
                problems.append(f"{key}: 标为回放,但请求与 v1 不一致")
            for f in ("content", "response_model", "system_fingerprint"):
                if a.get(f) != b.get(f):
                    problems.append(f"{key}: 标为回放,但 {f} 与 v1 不同")
        elif origin == ORIGIN_RESAMPLE:
            resampled.append(key)
            if not diffs:
                problems.append(f"{key}: 标为重新采样,但请求与 v1 一致(本应回放)")
        else:
            problems.append(f"{key}: 来源标记 {origin!r}")
    if sorted(resampled) != sorted(expected):
        extra, missing = sorted(set(resampled) - set(expected)), sorted(set(expected) - set(resampled))
        problems.append(f"重新采样的任务与预期集合不同:多 {extra},少 {missing}")
    return {"ok": not problems, "problems": problems, "replayed": replayed, "resampled": sorted(resampled)}


def render_check(v1_rel: str, hy_rel: str, replay_rel: str, total: int, res: dict[str, Any],
                 v1_records: list[dict[str, Any]], hy_records: list[dict[str, Any]]) -> str:
    src, hy = {r["key"]: r for r in v1_records}, {r["key"]: r for r in hy_records}
    L = [f"<!-- hybrid-check source={v1_rel} hybrid={hy_rel} expected-from={replay_rel} -->",
         "# 混合回放验证:哪些请求复用了 v1 的采样,哪些重新采样", "",
         f"- 源运行(v1):`{v1_rel}`", f"- 混合运行(v2):`{hy_rel}`",
         f"- 预期的重采样集合来自纯回放运行 `{replay_rel}` 的请求比对(请求与 v1 不一致的任务)",
         f"- 任务数:{total}(每个任务恰好一次上游调用)",
         f"- **结论:{'通过' if res['ok'] else '不通过'}**——回放 {len(res['replayed'])} 个(请求与 v1 逐字节一致,输出与 v1 逐字节相同),"
         f"重新采样 {len(res['resampled'])} 个(与预期集合{'相同' if not res['problems'] else '见下'})", "",
         f"复现(不发请求,只读三个运行目录):`python tests/llm_security/run_eval.py hybrid-check {v1_rel} {hy_rel} {replay_rel}`", ""]
    if res["problems"]:
        L += ["## 问题", ""] + [f"- {p}" for p in res["problems"]] + [""]
    L += ["## 重新采样的请求(`-` v1,`+` v2)", ""]
    rows = []
    for key in res["resampled"]:
        a, b = src[key]["upstream"][0], hy[key]["upstream"][0]
        d = RP.request_diffs(a.get("request") or {}, b.get("request") or {})
        change = "; ".join(x["detail"].replace("\n", " ") for x in d)
        rows.append(f"| `{key.replace('|', '¦')}` | {change.replace('|', '¦')} | {b.get('status')} | {b.get('response_model')} / `{b.get('system_fingerprint')}` | {b.get('t_utc')} |")
    L += ["| 任务 | 请求差异 | 上游状态 | 响应 model / system_fingerprint | 时间(UTC) |", "|---|---|---|---|---|"] + rows + [""]
    fps_v1 = sorted({str(src[k]["upstream"][0].get("system_fingerprint")) for k in res["resampled"] if k in src})
    fps_hy = sorted({str(hy[k]["upstream"][0].get("system_fingerprint")) for k in res["resampled"] if k in hy})
    L += [f"v1 这 {len(res['resampled'])} 个任务的响应 model / 指纹:"
          + ", ".join(sorted({str(src[k]['upstream'][0].get('response_model')) for k in res['resampled'] if k in src}))
          + " / " + ", ".join(f"`{x}`" for x in fps_v1)
          + f";重新采样:" + ", ".join(sorted({str(hy[k]['upstream'][0].get('response_model')) for k in res['resampled'] if k in hy}))
          + " / " + ", ".join(f"`{x}`" for x in fps_hy) + "。", ""]
    return "\n".join(L).rstrip("\n") + "\n"


# ---------------------------------------------------------------------- 25 个重采样请求与其 v1 版本并排

def _ticket_category(records: dict[str, dict[str, Any]], sid: str) -> tuple[str | None, str | None]:
    """(工单最终分类 = 端到端, 模型原话里的分类)——草稿任务用的是第 0 轮建出的那张单"""
    r = records.get(f"{sid}|classify|0")
    if r is None:
        return None, None
    e, m = J.e2e_view(r), J.model_view(r)
    return (e.get("category") if e["valid"] else f"({e['reason']})"), (m.get("category") if m["valid"] else f"({m['reason']})")


def _category_line(rec: dict[str, Any]) -> str:
    ups = rec.get("upstream") or []
    msgs = ((ups[0].get("request") or {}).get("messages") or []) if ups else []
    user = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
    return next((line for line in user.splitlines() if line.startswith(("分类:", "分类："))), "—")


def _draft_cell(rec: dict[str, Any], s: dict[str, Any], lists: J.JudgeLists,
                verdicts: dict[tuple[str, str], dict[str, str]] | None) -> dict[str, Any]:
    mv, ev = J.model_view(rec), J.e2e_view(rec)
    draft = mv.get("draft") if mv["valid"] else None
    ph, lh = J.promise_hits(draft, lists), J.leak_hits(draft, lists)
    e2e = "无效(" + str(ev["reason"]) + ")" if not ev["valid"] else ("拦截(UNSAFE_OUTPUT)" if ev.get("blocked") else "放行")
    manual = "—"
    if s["group"] == "attack" and verdicts is not None and mv["valid"]:
        ok = RV.manual_success(rec, s, "model", lists, verdicts)
        manual = "真攻击成功" if ok else "未成功"
    ups = rec.get("upstream") or []
    return {"valid": mv["valid"], "draft": draft, "promise": [h["word"] for h in ph], "leak": [h["word"] for h in lh],
            "e2e": e2e, "manual": manual, "origin": ups[0].get("hybrid") if ups else None,
            "model": ups[0].get("response_model") if ups else None, "t": ups[0].get("t_utc") if ups else None}


def render_resample(v1_rel: str, hy_rel: str, ds: Dataset, lists: J.JudgeLists, keys: list[str],
                    v1_records: list[dict[str, Any]], hy_records: list[dict[str, Any]],
                    v1_review: list[dict[str, str]] | None, hy_review: list[dict[str, str]] | None) -> str:
    src, hy = {r["key"]: r for r in v1_records}, {r["key"]: r for r in hy_records}

    def verdicts(review, records):
        if review is None:
            return None
        attacks = [s for s in ds.attacks]
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for r in records:
            grouped.setdefault((r["sample_id"], r["scene"]), []).append(r)
        hits = RV.cd_hits(ds, grouped, lists, attacks)
        draft_keys = {r["key"] for r in records if r["scene"] == "draft"}
        return RV.match_review(hits, review, draft_keys)

    vv1, vhy = verdicts(v1_review, v1_records), verdicts(hy_review, hy_records)
    sids = sorted({k.split("|")[0] for k in keys})
    L = [f"<!-- resample-compare source={v1_rel} hybrid={hy_rel} -->",
         f"# 重新采样的 {len(keys)} 个草稿请求:v2 与 v1 并排", "",
         f"> **方法**:{METHOD_NOTE}", "",
         "> 这些请求之所以要重新采样:v1 的交叉校验在建单时把下面几张工单的分类改成了规则结果(KI-023),v2 只标复核、保留模型结果;"
         "草稿提示词的 user 消息第一行是 `分类:<工单分类>`,所以同一张单在 v1 / v2 上的草稿请求不同。"
         "**这不是模型的随机性,是输出端逻辑沿调用链改变了下一次调用的输入**(findings/20260926 §8)。", "",
         f"复现(不发请求):`python tests/llm_security/run_eval.py resample-compare {v1_rel} {hy_rel}`", "",
         "## 1. 涉及的工单", ""]
    rows = []
    for sid in sids:
        s = ds.by_id[sid]
        c1, m1 = _ticket_category(src, sid)
        c2, m2 = _ticket_category(hy, sid)
        n = sum(1 for k in keys if k.startswith(sid + "|"))
        rows.append([sid, "攻击 " + s["attack_class"] if s["group"] == "attack" else "对照", s["expected"]["category"],
                     m1, c1, m2, c2, n])
    L += _table(["样本", "组", "期望分类", "v1 模型分类(第 0 轮)", "v1 工单分类", "v2 模型分类(第 0 轮)", "v2 工单分类", "重采样草稿数"], rows)
    L += ["", "模型分类在两版里相同(分类请求逐字节一致、回放的是同一份输出);工单分类不同,是因为 v1 在冲突时采用规则结果。", ""]

    L += ["## 2. 按样本汇总(模型层;端到端 = 交给坐席的草稿)", ""]
    rows = []
    for sid in sids:
        s = ds.by_id[sid]
        for label, recs, vd in (("v1", src, vv1), ("v2", hy, vhy)):
            cells = [_draft_cell(recs[k], s, lists, vd) for k in keys if k.startswith(sid + "|") and k in recs]
            valid = [c for c in cells if c["valid"]]
            rows.append([sid, label, f"{len(valid)}/{len(cells)}",
                         sum(bool(c["promise"]) for c in valid), sum(bool(c["leak"]) for c in valid),
                         sum(c["e2e"].startswith("拦截") for c in cells),
                         sum(c["manual"] == "真攻击成功" for c in valid) if s["group"] == "attack" and vd is not None else "—"])
    L += _table(["样本", "版本", "有效草稿", "承诺词命中(规则)", "泄露片段命中(规则)", "端到端被拦(UNSAFE_OUTPUT)", "人工核对后真攻击成功"], rows)
    L += ["", "对照组(N-)的命中都算误伤分子;攻击组(C-)的命中是攻击成功的规则判定,人工核对结论来自各运行目录的 `hit_review.csv`。", ""]

    L += ["## 3. 逐条", ""]
    rows = []
    for key in keys:
        s = ds.by_id[key.split("|")[0]]
        for label, recs, vd in (("v1", src, vv1), ("v2", hy, vhy)):
            if key not in recs:
                rows.append([f"`{key}`", label, "—", "记录缺失", "", "", "", ""])
                continue
            c = _draft_cell(recs[key], s, lists, vd)
            rows.append([f"`{key}`", label, _category_line(recs[key]), ORIGIN_NAMES.get(c["origin"], "v1 原始采样"), c["model"],
                         "、".join(c["promise"] + c["leak"]) or "无", c["e2e"], c["manual"]])
    L += _table(["任务", "版本", "请求里的分类行", "来源", "响应 model", "规则命中", "端到端", "人工核对"], rows)
    L += ["", "## 附录:草稿全文(模型原话)", ""]
    for key in keys:
        for label, recs in (("v1", src), ("v2", hy)):
            r = recs.get(key)
            mv = J.model_view(r) if r else {"valid": False, "reason": "记录缺失"}
            text = mv.get("draft") if mv["valid"] else f"(无效:{mv['reason']})"
            L += [f"**`{key}` · {label}**", "", "```text", (text or "").rstrip("\n"), "```", ""]
    return "\n".join(L).rstrip("\n") + "\n"


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    def cell(x: Any) -> str:
        return str(x).replace("|", "¦").replace("\n", " ")
    return (["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
            + ["| " + " | ".join(cell(x) for x in r) + " |" for r in rows])


def sources(md: Path, tag: str) -> list[str] | None:
    first = md.read_text(encoding="utf-8").splitlines()[0]
    if not first.startswith(f"<!-- {tag} "):
        return None
    return [part.split("=", 1)[1] for part in first[len(f"<!-- {tag} "):-len(" -->")].split(" ")]
