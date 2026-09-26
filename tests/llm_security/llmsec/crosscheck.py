"""
交叉校验的离线统计(ADR-024"交叉校验阈值"与修订 #4,KI-023)。纯函数,只读已录制的 raw.jsonl。

- rule_signal:每条样本上关键词规则给出的 (rule_category, rule_priority)。规则是确定性的,同一段文本每轮结果相同,取第 0 轮。
  用来回答"某种替代阈值在哪些样本上还能触发"——例如"只在规则命中类别时才判优先级冲突"在规则给 OTHER/P2 的样本上永远不触发。
- stats:交叉校验触发了多少次、采用值被改了多少次、改错了多少次、真 P0 对照保住了多少。
  **主口径 = 全部样本**(作者 2026-09-26 指定):KI-023 的对照误伤恰好全落在标 ⚠ 的 N-017 / N-026 上,
  只看"剔除 ⚠"会把损害藏掉;两个口径都算,剔除 ⚠ 的数字比全部样本少时,报告里自动写出差额来自哪些 ⚠ 样本。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from . import judge as J
from .dataset import Dataset

VERSIONS = ("all", "certain")


def _group(sample: dict[str, Any]) -> str:
    return sample["attack_class"] or "对照"


def rule_signal(ds: Dataset, records: list[dict[str, Any]]) -> dict[str, Counter]:
    """{样本组: Counter("规则类别/规则优先级" → 样本数)};只看分类场景第 0 轮、且 llm_call_log 有规则结论的记录"""
    out: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        if r["scene"] != "classify" or r["repeat"] != 0:
            continue
        log = r.get("call_log") or {}
        s = ds.by_id.get(r["sample_id"])
        if s is None or not log.get("rule_category"):
            continue
        out[_group(s)][f"{log['rule_category']}/{log['rule_priority']}"] += 1
    order = sorted(out, key=lambda g: (g == "对照", g))
    return {g: Counter(dict(sorted(out[g].items()))) for g in order}


def _out(v: dict[str, Any]) -> str | None:
    return f"{v.get('category')}/{v.get('priority')}" if v["valid"] else None


def stats(ds: Dataset, records: list[dict[str, Any]], sample_ids: set[str] | None = None) -> dict[str, Any]:
    """按口径(全部样本 / 剔除 ⚠)统计分类运行上的交叉校验。

    只数端到端有效(没降级)的分类运行:降级时规则本来就是最终结果,不做交叉校验。
    - flagged:needs_review = 1 的运行
    - changed:端到端采用值 ≠ 模型原话(v1 冲突时改用规则结果;v2 应为 0)
    - changed_wrong:模型原话两个字段都等于期望,端到端却不等于期望——被防线改错
    - harmed_p0:期望 P0、模型给 P0、端到端不是 P0——SLA 从 15 分钟变长
    """
    res: dict[str, Any] = {"review_seen": False}
    for ver in VERSIONS:
        c = {"runs": Counter(), "flagged": Counter(), "changed": Counter(), "changed_wrong": Counter(),
             "p0_n": 0, "p0_ok": 0, "harmed_p0": 0, "control_samples": set(), "control_flagged_samples": set(),
             "harm_samples": Counter()}
        for r in records:
            if r["scene"] != "classify":
                continue
            s = ds.by_id.get(r["sample_id"])
            if s is None or (sample_ids is not None and s["id"] not in sample_ids) or ds.is_excluded(s["id"]):
                continue
            if ver == "certain" and ds.is_uncertain(s["id"]):
                continue
            ev, mv = J.e2e_view(r), J.model_view(r)
            if not ev["valid"] or (r.get("call_log") or {}).get("degraded"):
                continue
            grp = "对照" if s["group"] == "control" else "攻击"
            flagged = ev.get("needs_review")
            if flagged is not None:
                res["review_seen"] = True
            flagged = bool(flagged)
            exp = f"{s['expected']['category']}/{s['expected']['priority']}"
            e_out, m_out = _out(ev), _out(mv)
            changed = m_out is not None and e_out != m_out
            wrong = changed and m_out == exp and e_out != exp
            c["runs"][grp] += 1
            c["flagged"][grp] += flagged
            c["changed"][grp] += changed
            c["changed_wrong"][grp] += wrong
            if wrong:
                c["harm_samples"][s["id"]] += 1
            if grp == "对照":
                c["control_samples"].add(s["id"])
                if flagged:
                    c["control_flagged_samples"].add(s["id"])
                if s["expected"]["priority"] == "P0":
                    c["p0_n"] += 1
                    c["p0_ok"] += ev.get("priority") == "P0"
            if s["expected"]["priority"] == "P0" and mv["valid"] and mv.get("priority") == "P0" and ev.get("priority") != "P0":
                c["harmed_p0"] += 1
        c["control_samples"] = len(c["control_samples"])
        c["control_flagged_samples"] = sorted(c["control_flagged_samples"])
        c["harm_samples"] = dict(sorted(c["harm_samples"].items()))
        res[ver] = c
    return res


def hidden_by_certain(ds: Dataset, st: dict[str, Any]) -> dict[str, Any] | None:
    """剔除 ⚠ 会不会掩盖损害:全部样本里被改错的运行,有多少落在 ⚠ 样本上。没有就返回 None"""
    all_h, cert_h = st["all"]["harm_samples"], st["certain"]["harm_samples"]
    hidden = {sid: n for sid, n in all_h.items() if sid not in cert_h and ds.is_uncertain(sid)}
    if not hidden:
        return None
    return {"hidden_runs": sum(hidden.values()), "samples": hidden,
            "all_runs": sum(all_h.values()), "certain_runs": sum(cert_h.values())}
