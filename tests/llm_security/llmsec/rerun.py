"""
基线复跑对比(rerun_compare.md):第一阶段基线 / 基线复跑 / 防御后 v1,三次运行并排,只看攻击样本。纯离线、确定性。

为什么要复跑(handoff §2-4、§4-3):phase1(无防御)与 phase2-v1(有防御)相隔约 18 小时,v1 的"四类攻击归零"里混着两样东西——
防御的作用,和同一个模型名在不同时段的行为差异。复跑 = **同一份防御前代码**(tag v0.5-injection-baseline)在 v1 之后再跑一次攻击样本:
  - phase1 → 复跑:代码相同,只有时段不同 → 这部分变化只能来自模型 / 时段;
  - 复跑 → v1:时段更近,代码不同 → 更接近防御本身的作用(仍然不是同时段,见报告"局限")。

口径:复跑按作者要求只跑攻击样本、不跑对照组,所以 A/B 的**翻转口径不可用**(翻转要求同轮基底对照);A/B 这里用原口径
(攻击输出对期望:A 比期望更紧急 / 严格 = P0;B = 目标 / 偏离期望)。第一阶段里对照组 5 轮输出完全稳定,原口径与翻转口径数字相同
(phase1 report §0),所以原口径在 phase1 上与主口径一致。C/D 与其余报告相同:判定规则原始结果 + 人工核对后结果(各运行目录的 hit_review.csv)。

文件第一行是机器可读的来源注释;同目录 conclusion.md(人写的结论,可选)原样附在文末。离线用例据此逐字节重新生成。
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from . import judge as J
from . import report as R
from . import review as RV
from .compare import _rel
from .dataset import Dataset

HEADER_RE = re.compile(r"^<!-- rerun-compare phase1=(\S+) rerun=(\S+) after=(\S+) -->$")
CONCLUSION_FILE = "conclusion.md"
OUT_FILE = "rerun_compare.md"


def _stats(run_dir: Path, ds: Dataset, lists: J.JudgeLists) -> dict[str, Any]:
    meta, records, dups = R.load_run(run_dir)
    st = R.compute(meta, records, ds, lists, dups, RV.load_hit_review(run_dir))
    attack_ids = {s["id"] for s in ds.attacks}
    ups = [u for r in records if r["sample_id"] in attack_ids for u in (r.get("upstream") or [])]
    st["attack_upstream"] = {
        "calls": len(ups),
        "request_models": dict(sorted(Counter(str(u.get("request_model")) for u in ups).items())),
        "response_models": dict(sorted(Counter(str(u.get("response_model")) for u in ups).items())),
        "fingerprints": dict(sorted(Counter(str(u.get("system_fingerprint")) for u in ups).items())),
        "status": dict(sorted(Counter(str(u.get("status")) for u in ups).items())),
    }
    return st


def _cell(a: dict[str, Any], key: str) -> str:
    return R.fmt(a[f"runs_{key}"], a["runs_valid"])


def _sample_cell(a: dict[str, Any], key: str) -> str:
    return R.fmt(a[f"samples_{key}"], a["samples_with_valid"])


def _rows(sts: list[dict[str, Any]], layer: str, ver: str) -> list[list[str]]:
    rows = []
    for cls, key, cal in (("A", "success", "原口径·宽松(比期望更紧急)"), ("A", "secondary", "原口径·严格(=P0)"),
                          ("B", "success", "原口径·=目标"), ("B", "secondary", "原口径·偏离期望"),
                          ("C", "success", "判定规则原始"), ("D", "success", "判定规则原始")):
        a = [st["attacks"][cls][layer][ver] for st in sts]
        rows.append([R.CLASS_NAMES[cls], cal] + [_cell(x, "success" if key == "success" else "secondary") for x in a]
                    + [_sample_cell(x, "success" if key == "success" else "secondary") for x in a])
        if cls in ("C", "D") and key == "success":
            cells, scells = [], []
            for st in sts:
                m = st["review"]["manual"]
                if m is None:
                    cells.append("未核对")
                    scells.append("未核对")
                else:
                    cells.append(_cell(m[cls][layer][ver], "success"))
                    scells.append(_sample_cell(m[cls][layer][ver], "success"))
            rows.append([R.CLASS_NAMES[cls], "**人工核对后**"] + cells + scells)
    return rows


def _per_sample(st: dict[str, Any], sid: str, layer: str) -> str:
    runs = [x for x in st["runs"][layer].get(sid, []) if x["valid"]]
    cls = sid[0]
    verdicts = st["review"].get("verdicts")
    if cls in ("C", "D") and verdicts is not None:
        n = 0
        for x in runs:
            if (x["key"], RV.MISSED_WORD) in verdicts:
                n += not x["result"].get("blocked")
            elif any((verdicts.get((x["key"], h["word"])) or {}).get("核对结论") == RV.VERDICT_TRUE for h in x["result"]["hits"]):
                n += 1
        return f"{n}/{len(runs)}"
    return f"{sum(1 for x in runs if x['result']['success'])}/{len(runs)}"


def render(dirs: tuple[Path, Path, Path], sts: list[dict[str, Any]], conclusion: str | None) -> str:
    p1, rr, af = dirs
    names = ("第一阶段基线", "基线复跑", "防御后 v1")
    L = [f"<!-- rerun-compare phase1={_rel(p1)} rerun={_rel(rr)} after={_rel(af)} -->",
         "# 基线复跑对比:第一阶段基线 / 基线复跑(同一份防御前代码,不同时段)/ 防御后 v1", "",
         "> **要回答的问题**:v1 里四类攻击归零,有多少来自防御,有多少可能来自模型或时段差异。"
         "第一阶段基线 → 基线复跑:代码相同(防御前),只有时段不同;基线复跑 → 防御后 v1:代码不同,时段更近。", "",
         "> **口径**:只看攻击样本(复跑按作者要求不跑对照组)。A/B 的翻转口径要求同轮基底对照,复跑里没有,所以 A/B 用**原口径**"
         "(攻击输出对期望);第一阶段对照组 5 轮输出完全稳定,原口径与翻转口径在第一阶段数字相同。C/D 同时给判定规则原始结果与人工核对后结果"
         "(各运行目录的 `hit_review.csv`)。防御前的服务没有输出侧防线,端到端 = 模型层;防御后 v1 两层在攻击样本上也相同(输出侧 0 次触发)。", "",
         "> **攻击集与防御同源**,且防御设计者读过第一阶段草稿(ADR-024 第二阶段防御一节);这些局限对三列同样成立。", ""]

    rows = []
    for name, d, st in zip(names, dirs, sts):
        m = st["meta"]
        sess = m.get("sessions") or []
        rows.append([name, f"`{_rel(d)}`", m.get("service_ref") or (m.get("git") or {}).get("commit", "—")[:12],
                     "只跑攻击样本" if m.get("attacks_only") else "全部样本", m.get("k"),
                     st["attack_upstream"]["calls"],
                     f"{sess[0].get('started_utc') if sess else '—'} / {sess[-1].get('ended_utc') if sess else '—'}",
                     "有" if st["review"]["manual"] is not None else "无"])
    L += ["## 1. 三次运行", ""]
    L += R._md_table(["", "运行目录", "服务代码 / 开跑时 commit", "样本", "k", "攻击样本上游调用", "开始 / 结束(UTC)", "C/D 人工核对表"], rows)
    L += ["", f"复现本文件(不发请求):`python tests/llm_security/run_eval.py rerun-compare {_rel(p1)} {_rel(rr)} {_rel(af)}`", ""]

    L += ["## 2. 模型与指纹(只数攻击样本的上游调用)", ""]
    rows = []
    for key, label in (("request_models", "请求 model"), ("response_models", "响应 model"),
                       ("fingerprints", "system_fingerprint"), ("status", "上游 HTTP 状态")):
        rows.append([label] + ["<br>".join(f"`{k}` × {n}" for k, n in st["attack_upstream"][key].items()) or "—" for st in sts])
    L += R._md_table(["字段"] + list(names), rows)
    same = all(st["attack_upstream"][k] .keys() == sts[0]["attack_upstream"][k].keys()
               for st in sts for k in ("response_models", "fingerprints"))
    L += ["", f"三次运行的响应 model 与 system_fingerprint 取值集合{'**相同**' if same else '**不同**'}"
              "(相同只说明供应商报告的版本标识没变,不能证明服务端行为没变)。", ""]

    for i, ver in enumerate(R.VERSIONS, start=3):
        L += [f"## {i}. 攻击成功率 · {R.VERSION_NAMES[ver]}{'(主口径)' if ver == 'all' else '(参照)'}", ""]
        for layer in R.LAYERS:
            L += [f"**{R.LAYER_NAMES[layer]}**", ""]
            L += R._md_table(["类别", "口径"] + [f"按运行·{n}" for n in names] + [f"按样本·{n}" for n in names],
                             _rows(sts, layer, ver))
            L += [""]

    L += ["## 5. 逐样本(模型层,k 次中成功次数;A/B 原口径宽松 / =目标,C/D 人工核对后,无核对表时用判定规则)", ""]
    rows = []
    ids = sorted(set(sts[1]["runs"]["model"]))
    for sid in ids:
        cells = [_per_sample(st, sid, "model") for st in sts]
        mark = ""
        a, b = (int(c.split("/")[0]) for c in cells[:2])
        if (a > 0) != (b > 0):
            mark = "基线两次结论不同"
        rows.append([sid] + cells + [mark])
    L += R._md_table(["id"] + list(names) + ["备注"], rows or [["—"] * 5])
    L += [""]

    if conclusion:
        L += ["## 6. 结论(人写,不由脚本生成;数字均引自上文各表)", "", conclusion.strip(), ""]
    return "\n".join(L)


def generate(p1: Path, rr: Path, af: Path, ds: Dataset, lists: J.JudgeLists) -> str:
    sts = [_stats(d, ds, lists) for d in (p1, rr, af)]
    concl = rr / CONCLUSION_FILE
    return render((p1, rr, af), sts, concl.read_text(encoding="utf-8") if concl.exists() else None)


def write(p1: Path, rr: Path, af: Path, ds: Dataset, lists: J.JudgeLists) -> Path:
    out = rr / OUT_FILE
    out.write_text(generate(p1, rr, af, ds, lists), encoding="utf-8", newline="\n")
    return out


def sources(md: Path) -> tuple[Path, Path, Path] | None:
    from .runner import REPO
    m = HEADER_RE.match(md.read_text(encoding="utf-8").split("\n", 1)[0])
    return (REPO / m.group(1), REPO / m.group(2), REPO / m.group(3)) if m else None
