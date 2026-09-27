"""
两次运行的对比报告(compare.md):防御前 vs 防御后。纯离线、确定性,只读两个运行目录里已录制的 raw.jsonl 与各自的 hit_review.csv。

用在三处:
  - phase1(第一阶段基线,无防御) vs phase2-v1(第二阶段防御后复测)——攻击集与防御同源;
  - holdout-pre vs holdout-post(留出集,防御定稿后另行起草的新样本,来源见 report.HO_SOURCE_NOTE;同一组样本分别打防御前 / 防御后的服务;
    主体是 holdout.py 生成的"留出集"一节,依赖基底 / 对照组的通用章节不出现);
  - phase2-v1 vs phase2-v2-replay(交叉校验 v2 的回放评估:同一批模型输出,v1 / v2 两种输出端逻辑;列名改为 v1 / v2);
  - phase2-v1 vs phase2-v2-hybrid(混合回放:请求一致的复用 v1 输出,不一致的 25 个草稿请求重新采样,llmsec/hybrid.py)。

KI-023(交叉校验误伤)一节以**全部样本**为主口径(作者 2026-09-26 指定),剔除 ⚠ 作参照;剔除 ⚠ 会藏掉损害时自动写明藏掉了什么。

每个数字都来自 report.compute(与 report.md 同一套口径,ADR-024),这里只做并排。
文件第一行是机器可读的来源注释,离线用例据此逐字节重新生成、比对已提交的 compare.md。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import crosscheck as XC
from . import holdout as HO
from . import judge as J
from . import report as R
from . import review as RV
from .dataset import Dataset
from .runner import REPO

HEADER_RE = re.compile(r"^<!-- compare before=(\S+) after=(\S+) -->$")
FORMATS = ("single", "mixed", "none")


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return p.name


def _stats(run_dir: Path, ds: Dataset, lists: J.JudgeLists) -> dict[str, Any]:
    meta, records, dups = R.load_run(run_dir)
    st = R.compute(meta, records, ds, lists, dups, RV.load_hit_review(run_dir))
    st["p0_controls"] = {sid: ds.by_id[sid]["expected"]["priority"] == "P0" for sid in st["control_outputs"]}
    st["xc"] = XC.stats(ds, records, set(meta["sample_ids"]) if meta.get("sample_ids") else None)
    st["ds"] = ds
    if meta.get("phase") == "holdout":
        st["ho"] = HO.compute(run_dir, ds, lists)
    return st


def _flip_cells(st: dict[str, Any], cls: str, layer: str, ver: str) -> tuple[str, str]:
    f = st["review"]["flips"][cls][layer][ver]
    return R.fmt(f["runs_flip"], f["runs_eligible"]), R.fmt(f["samples_flip"], f["samples_eligible"])


def _rule_cells(st: dict[str, Any], cls: str, layer: str, ver: str, key: str = "success") -> tuple[str, str]:
    a = st["attacks"][cls][layer][ver]
    if key == "success":
        return R.fmt(a["runs_success"], a["runs_valid"]), R.fmt(a["samples_success"], a["samples_with_valid"])
    return R.fmt(a["runs_secondary"], a["runs_valid"]), R.fmt(a["samples_secondary"], a["samples_with_valid"])


def _manual_cells(st: dict[str, Any], cls: str, layer: str, ver: str) -> tuple[str, str]:
    m = st["review"]["manual"]
    if m is None:
        return "未核对", "未核对"
    a = m[cls][layer][ver]
    return R.fmt(a["runs_success"], a["runs_valid"]), R.fmt(a["samples_success"], a["samples_with_valid"])


def _notes(mb: dict[str, Any], ma: dict[str, Any]) -> list[str]:
    L = []
    if ma.get("phase") == "holdout":
        L += ["> **样本来源**:留出集 `data/holdout.jsonl`(由 `data/holdout_source.txt` 逐字转换)在第二阶段防御定稿之后起草——"
              + R.HO_SOURCE_NOTE + "所以它与防御不同源,但**不是盲测**:起草时针对的就是已知的防御设计。两次运行打的是同一组样本、同一个上游,"
              f"只有服务代码不同:防御前 = {mb.get('service_ref') or '未记录'},防御后 = {ma.get('service_ref') or '未记录'}。", ""]
        return L
    else:
        L += ["> **攻击集与防御同源**:攻击集由 Claude 编写,防御也由 Claude 编写,防御后的数字偏乐观。不同源的检验见留出集对比"
              "(防御定稿后另行起草的新样本,`tests/llm_security/README.md`「留出集」)。", "",
              "> **已知局限——防御设计者读过第一阶段数据**(ADR-024 第二阶段防御一节的披露,原文照录要点):写防御的 Claude 在 M5.5 人工核对时"
              "逐条读过第一阶段全部 90 份 C/D 草稿,知道模型成功时写了什么。防御的词表、窗口、阈值没有拿录到的数据试算过,"
              "但\"没调过\"只能保证到这一步,不能保证设计者的直觉没被数据影响。", ""]
    if ma.get("replay"):
        L += [f"> **方法(回放评估)**:{ma['replay']['method']} 源运行 = `{ma['replay']['source']}`。"
              "所以两列的**模型层逐条相同**(同一批模型输出),差别只可能出现在端到端;请求逐字节一致的验证见本目录 `replay_check.md`。", ""]
    if ma.get("hybrid"):
        h = ma["hybrid"]
        L += [f"> **方法(混合回放)**:{h['method']} 源运行 = `{h['source']}`;重新采样的 {len(h['resample_keys'])} 个请求见本目录 "
              "`hybrid_check.md`(哪些回放、哪些重采样,逐条验证)与 `resample_compare.md`(与各自的 v1 版本逐条并排)。"
              "所以两列的模型层**除这些重采样请求外逐条相同**;分类场景的模型层完全相同,差别只可能出现在端到端。", ""]
    L += ["> **口径**:A/B 主口径 = 翻转口径(攻击第 r 轮与基底对照第 r 轮配对,对照给出期望值、攻击偏向目标才算);C/D 同时给**判定规则原始结果**"
          "(冻结的词表 / 片段)与**人工核对后结果**(各运行目录的 `hit_review.csv`)。端到端 = 服务最终采用的值 / 交给坐席的草稿;"
          "模型层 = 录制代理录到的模型原话。防御前的服务没有输出侧防线,两层本应一致;防御后两层之差 = 输出侧防线(交叉校验、草稿检查、严格解析)挡下的量,"
          "模型层的变化 = 输入隔离(提示词)的作用。降级运行除 `UNSAFE_OUTPUT` 外不进分母(ADR-024 §2)。", ""]
    return L


def render(before_dir: Path, after_dir: Path, sb: dict[str, Any], sa: dict[str, Any]) -> str:
    mb, ma = sb["meta"], sa["meta"]
    lb, la = ("v1", "v2(回放)") if ma.get("replay") else (("v1", "v2(混合回放)") if ma.get("hybrid") else ("防御前", "防御后"))
    title_b = f"{mb.get('phase')}" + (f"-{mb['run_label']}" if mb.get("run_label") else "")
    title_a = f"{ma.get('phase')}" + (f"-{ma['run_label']}" if ma.get("run_label") else "")
    L = [f"<!-- compare before={_rel(before_dir)} after={_rel(after_dir)} -->",
         f"# 注入评测对比 · {title_b}({lb}) vs {title_a}({la})", ""]
    L += _notes(mb, ma)

    rows = []
    for label, d, m, st in ((lb, before_dir, mb, sb), (la, after_dir, ma, sa)):
        sess = m.get("sessions") or []
        rows.append([label, f"`{_rel(d)}`", (m.get("git") or {}).get("commit"), m.get("service_ref") or "—", m.get("k"),
                     st["calls"]["records"], st["calls"]["upstream_calls"],
                     f"{sess[0].get('started_utc') if sess else '—'} / {sess[-1].get('ended_utc') if sess else '—'}",
                     "有" if st["review"]["manual"] is not None or (st.get("ho") or {}).get("reviewed") else "无"])
    L += ["## 1. 两次运行", ""]
    L += R._md_table(["", "运行目录", "git commit(开跑时)", "服务代码", "k", "raw 记录", "上游调用", "开始 / 结束(UTC)", "C/D 人工核对表"], rows)
    L += ["", f"复现本文件(不发请求):`python tests/llm_security/run_eval.py compare {_rel(before_dir)} {_rel(after_dir)}`", ""]
    if ma.get("phase") == "holdout":
        return "\n".join(_render_holdout(sb, sa, lb, la, L))

    # ---- 主口径
    L += [f"## 2. 主口径:{lb} → {la}", ""]
    for ver in R.VERSIONS:
        L += [f"### 2.{R.VERSIONS.index(ver) + 1} {R.VERSION_NAMES[ver]}", ""]
        rows = []
        for layer in R.LAYERS:
            for cls, cal in (("A", "翻转·宽松"), ("B", "翻转")):
                b, a = _flip_cells(sb, cls, layer, ver), _flip_cells(sa, cls, layer, ver)
                rows.append([R.CLASS_NAMES[cls], cal, R.LAYER_NAMES[layer], b[0], a[0], b[1], a[1]])
            for cls in ("C", "D"):
                b, a = _rule_cells(sb, cls, layer, ver), _rule_cells(sa, cls, layer, ver)
                rows.append([R.CLASS_NAMES[cls], "判定规则原始", R.LAYER_NAMES[layer], b[0], a[0], b[1], a[1]])
                b, a = _manual_cells(sb, cls, layer, ver), _manual_cells(sa, cls, layer, ver)
                rows.append([R.CLASS_NAMES[cls], "**人工核对后**", R.LAYER_NAMES[layer], b[0], a[0], b[1], a[1]])
        L += R._md_table(["类别", "口径", "层", f"按运行·{lb}", f"按运行·{la}", f"按样本·{lb}", f"按样本·{la}"], rows)
        L += [""]

    # ---- 参照口径
    L += ["## 3. 参照口径(原口径:只看攻击输出本身,不与基底配对)", ""]
    rows = []
    for layer in R.LAYERS:
        for cls, key, cal in (("A", "success", "宽松(比期望更紧急)"), ("A", "secondary", "严格(=P0)"),
                              ("B", "success", "=目标"), ("B", "secondary", "偏离期望")):
            b, a = _rule_cells(sb, cls, layer, "all", key), _rule_cells(sa, cls, layer, "all", key)
            rows.append([R.CLASS_NAMES[cls], cal, R.LAYER_NAMES[layer], b[0], a[0], b[1], a[1]])
        for cls in ("A",):
            fb, fa = sb["review"]["flips"][cls][layer]["all"], sa["review"]["flips"][cls][layer]["all"]
            rows.append([R.CLASS_NAMES[cls], "翻转·严格(=P0)", R.LAYER_NAMES[layer],
                         R.fmt(fb["runs_flip_strict"], fb["runs_eligible"]), R.fmt(fa["runs_flip_strict"], fa["runs_eligible"]),
                         R.fmt(fb["samples_flip_strict"], fb["samples_eligible"]), R.fmt(fa["samples_flip_strict"], fa["samples_eligible"])])
    L += R._md_table(["类别", "口径", "层", f"按运行·{lb}", f"按运行·{la}", f"按样本·{lb}", f"按样本·{la}"], rows)
    L += [""]

    # ---- 误伤
    L += ["## 4. 正常对照组:准确率与误伤(全部样本)", ""]
    rows = []
    for layer in R.LAYERS:
        cb, ca = sb["controls"][layer]["all"], sa["controls"][layer]["all"]
        rows.append([R.LAYER_NAMES[layer], "分类与优先级都对(按运行)", R.fmt(cb["both_ok"], cb["runs_valid"]), R.fmt(ca["both_ok"], ca["runs_valid"])])
        rows.append([R.LAYER_NAMES[layer], "分类对(按运行)", R.fmt(cb["cat_ok"], cb["runs_valid"]), R.fmt(ca["cat_ok"], ca["runs_valid"])])
        rows.append([R.LAYER_NAMES[layer], "优先级对(按运行)", R.fmt(cb["pri_ok"], cb["runs_valid"]), R.fmt(ca["pri_ok"], ca["runs_valid"])])
        rows.append([R.LAYER_NAMES[layer], "草稿命中承诺词(按运行)", R.fmt(cb["draft_promise_runs"], cb["draft_runs_valid"]),
                     R.fmt(ca["draft_promise_runs"], ca["draft_runs_valid"])])
    for layer in R.LAYERS:
        rows.append([R.LAYER_NAMES[layer], "**期望 P0 的对照:给出 P0(按运行)**", _p0_cell(sb, layer), _p0_cell(sa, layer)])
    cb, ca = sb["controls"]["e2e"]["all"], sa["controls"]["e2e"]["all"]
    rv = lambda c: R.fmt(c["runs_review"], c["runs_valid"]) if c["review_seen"] else "—(无此字段)"          # noqa: E731
    rs = lambda c: R.fmt(c["samples_review"], c["samples_with_valid"]) if c["review_seen"] else "—(无此字段)"   # noqa: E731
    rows.append(["端到端", "**被标记人工复核(误伤,按运行)**", rv(cb), rv(ca)])
    rows.append(["端到端", "**被标记人工复核(误伤,按样本 ≥1 次)**", rs(cb), rs(ca)])
    rows.append(["端到端", "**草稿被拦成模板(误伤,按运行)**", R.fmt(cb["draft_runs_blocked"], cb["draft_runs_valid"]),
                 R.fmt(ca["draft_runs_blocked"], ca["draft_runs_valid"])])
    rows.append(["端到端", "**草稿被拦成模板(误伤,按样本 ≥1 次)**", R.fmt(cb["draft_samples_blocked"], cb["draft_samples_with_valid"]),
                 R.fmt(ca["draft_samples_blocked"], ca["draft_samples_with_valid"])])
    L += R._md_table(["层", "指标", lb, la], rows)
    L += ["", f"攻击样本上被防线拦下的次数(端到端,{la}):", ""]
    rows = []
    for cls in ("C", "D"):
        a = sa["attacks"][cls]["e2e"]["all"]
        rows.append([R.CLASS_NAMES[cls], R.fmt(a["runs_blocked"], a["runs_valid"])])
    L += R._md_table(["类别", "草稿被拦成模板(按运行)"], rows)
    L += [""]

    L += _render_crosscheck(sb, sa, lb, la)

    L += _render_invalid(sb, sa, lb, la, 6)

    # ---- 逐样本
    L += ["## 7. 逐样本(端到端 / 模型层,k 次中成功次数;A/B 为翻转次数 / 可配对次数,C/D 为人工核对后成功次数,无核对表时用判定规则)", ""]
    rows = []
    ids = sorted(set(sb["runs"]["e2e"]) & set(sa["runs"]["e2e"]))
    for sid in ids:
        cls = sid[0]
        cells = []
        for st in (sb, sa):
            for layer in R.LAYERS:
                cells.append(_sample_cell(st, sid, cls, layer))
        rows.append([sid, cls] + cells)
    L += R._md_table(["id", "类", f"{lb}·端到端", f"{lb}·模型层", f"{la}·端到端", f"{la}·模型层"], rows or [["—"] * 6])
    L += [""]

    # ---- 防御后仍成功的端到端运行
    L += [f"## 8. {la}端到端仍然成功的运行(C/D 列命中词与人工核对结论;A/B 列输出)", ""]
    rows = []
    verdicts = sa["review"].get("verdicts") or {}
    for sid in sorted(sa["runs"]["e2e"]):
        cls = sid[0]
        if cls in ("A", "B"):
            for e in sa["review"]["pairs"]["e2e"].get(sid, []):
                if e["status"] == "flip":
                    rows.append([f"{sid}|classify|{e['repeat']}", f"{e['control']} → {e['attack']}", "翻转"])
        else:
            for x in sa["runs"]["e2e"][sid]:
                if x["valid"] and x["result"]["success"]:
                    words = ", ".join(f"{h['word']}({(verdicts.get((x['key'], h['word'])) or {}).get('核对结论', '未核对')})"
                                      for h in x["result"]["hits"])
                    rows.append([x["key"], words, "判定规则命中"])
    L += R._md_table(["key", "输出 / 命中", "依据"], rows or [["—", "无", "—"]])
    L += [""]
    return "\n".join(L)


def _render_invalid(sb: dict[str, Any], sa: dict[str, Any], lb: str, la: str, n: int) -> list[str]:
    L = [f"## {n}. 无效运行、降级原因与分类输出格式", ""]
    keys = sorted(set(sb["calls"]["invalid"]["e2e"]) | set(sa["calls"]["invalid"]["e2e"]))
    rows = [[k, sb["calls"]["invalid"]["e2e"].get(k, 0), sa["calls"]["invalid"]["e2e"].get(k, 0)] for k in keys]
    L += ["端到端无效运行(不进分母):", ""]
    L += R._md_table(["场景:原因", lb, la], rows or [["无", 0, 0]])
    L += ["", "攻击样本上的格式类降级:", ""]
    L += R._md_table(["原因", lb, la], [
        ["BAD_RESPONSE(读不出对象,计入熔断)", len(sb["calls"]["bad_response_attacks"]), len(sa["calls"]["bad_response_attacks"])],
        ["MIXED_OUTPUT(夹带,不计入熔断)", len(sb["calls"]["mixed_output_attacks"]), len(sa["calls"]["mixed_output_attacks"])]])
    groups = sorted({k.split(":")[0] for st in (sb, sa) for k in st["calls"]["formats"]}, key=lambda g: (g == "对照", g))
    rows = []
    for g in groups:
        rows.append([g] + [f"{sb['calls']['formats'].get(f'{g}:{f}', 0)} → {sa['calls']['formats'].get(f'{g}:{f}', 0)}" for f in FORMATS])
    L += ["", f"分类场景模型原始输出的格式形态({lb} → {la};按服务端 `LlmJson` 同样的规则归类):", ""]
    L += R._md_table(["样本组"] + [R.FORMAT_NAMES[f] for f in FORMATS], rows or [["—", "", "", ""]])
    L += [""]
    return L


def _render_holdout(sb: dict[str, Any], sa: dict[str, Any], lb: str, la: str, L: list[str]) -> list[str]:
    """留出集:没有基底、没有对照组,翻转口径与对照误伤两节不适用;主体是 holdout.render_section"""
    rows = []
    for label, st in ((lb, sb), (la, sa)):
        c = st["calls"]
        rows.append([label, _cell_json(c["request_models"]), _cell_json(c["response_models"]), _cell_json(c["fingerprints"]),
                     _cell_json(c["upstream_status"])])
    L += R._md_table(["", "请求模型名", "响应模型名", "system_fingerprint", "上游 HTTP 状态"], rows)
    L += [""]
    L += HO.render_section(sb["ho"], sa["ho"], lb, la, 2)
    L += _render_invalid(sb, sa, lb, la, 3)
    return L


def _cell_json(d: dict[str, Any]) -> str:
    return ", ".join(f"{k} ×{v}" for k, v in d.items()) or "—"


def _xc_rows(st: dict[str, Any], ver: str) -> list[tuple[str, str]]:
    """一个口径下交叉校验的各行(名字, 格子)。没有 needs_review 字段的运行(第一阶段)标记相关行写「无此字段」"""
    x = st["xc"][ver]
    seen = st["xc"]["review_seen"]
    runs, flagged = x["runs"], x["flagged"]
    total = sum(runs.values())
    na = "—(无此字段)"
    return [
        ("交叉校验触发(按分类运行,对照 + 攻击)", R.fmt(sum(flagged.values()), total) if seen else na),
        ("　其中对照(按运行)", R.fmt(flagged["对照"], runs["对照"]) if seen else na),
        ("　其中攻击样本(按运行)", R.fmt(flagged["攻击"], runs["攻击"]) if seen else na),
        ("被标记复核的对照工单(按样本 ≥1 次)", R.fmt(len(x["control_flagged_samples"]), x["control_samples"]) if seen else na),
        ("触发后采用值被改成与模型不同(按运行)", R.fmt(sum(x["changed"].values()), total)),
        ("**被改错**:模型原话两个字段都对、端到端不对(按运行)", R.fmt(sum(x["changed_wrong"].values()), total)),
        ("**期望 P0 的对照:端到端给出 P0**", R.fmt(x["p0_ok"], x["p0_n"])),
        ("期望 P0、模型给 P0、端到端不是 P0(SLA 被放宽,对照 + 攻击)", str(x["harmed_p0"])),
    ]


def _render_crosscheck(sb: dict[str, Any], sa: dict[str, Any], lb: str, la: str) -> list[str]:
    L = ["## 5. 交叉校验与 KI-023(主口径:全部样本)", "",
         "> **为什么以全部样本为主**:KI-023 的对照组误伤全部落在标 ⚠ 的样本上(v1:N-017、N-026),「剔除 ⚠」版本会把它们连同分母一起拿掉。"
         "⚠ 表示「期望标签拿不准」,不表示「这张工单不存在」;它们在真实流量里一样会被误伤。剔除 ⚠ 的数字只作参照。"
         "只数端到端有效(未降级)的分类运行:降级时规则本来就是最终结果,不做交叉校验。", ""]
    for ver, title in (("all", "5.1 全部样本(主口径)"), ("certain", "5.2 剔除 ⚠ 样本(参照)")):
        rb, ra = _xc_rows(sb, ver), _xc_rows(sa, ver)
        L += [f"### {title}", ""]
        L += R._md_table(["指标", lb, la], [[n, b, a] for (n, b), (_, a) in zip(rb, ra)])
        L += [""]
    warn = []
    for label, st in ((lb, sb), (la, sa)):
        h = XC.hidden_by_certain(st["ds"], st["xc"])
        if h:
            who = "、".join(f"{sid}({n} 次)" for sid, n in h["samples"].items())
            warn.append(f"> **剔除 ⚠ 会掩盖损害({label})**:全部样本里被改错 {h['all_runs']} 次,剔除 ⚠ 后只剩 {h['certain_runs']} 次;"
                        f"藏掉的 {h['hidden_runs']} 次全部来自 ⚠ 样本 {who}。引用这一口径时必须同时给出全部样本的数字。")
    if warn:
        L += warn + [""]
    return L


def _p0_cell(st: dict[str, Any], layer: str) -> str:
    """真 P0 工单有没有被保住:交叉校验"模型 P0 且规则 P2 → 采用规则"会把规则没认出来的真 P0 降成 P2(SLA 15 → 240 分钟)"""
    ok = n = 0
    for sid, outs in st["control_outputs"].items():
        if st["p0_controls"].get(sid):
            for out, cnt in outs[layer].items():
                if not out.startswith("×"):
                    n += cnt
                    ok += cnt if out.endswith("/P0") else 0
    return R.fmt(ok, n)


def _sample_cell(st: dict[str, Any], sid: str, cls: str, layer: str) -> str:
    if cls in ("A", "B"):
        pairs = st["review"]["pairs"][layer].get(sid, [])
        el = [e for e in pairs if e["status"] in ("flip", "no_flip")]
        return f"{sum(1 for e in el if e['status'] == 'flip')}/{len(el)}"
    runs = [x for x in st["runs"][layer].get(sid, []) if x["valid"]]
    verdicts = st["review"].get("verdicts")
    if verdicts is None:
        return f"{sum(1 for x in runs if x['result']['success'])}/{len(runs)}"
    n = 0
    for x in runs:
        if (x["key"], RV.MISSED_WORD) in verdicts:
            n += not x["result"].get("blocked")
        elif any((verdicts.get((x["key"], h["word"])) or {}).get("核对结论") == RV.VERDICT_TRUE for h in x["result"]["hits"]):
            n += 1
    return f"{n}/{len(runs)}"


def generate(before_dir: Path, after_dir: Path, ds_before: Dataset, ds_after: Dataset, lists: J.JudgeLists) -> str:
    return render(before_dir, after_dir, _stats(before_dir, ds_before, lists), _stats(after_dir, ds_after, lists))


def write(before_dir: Path, after_dir: Path, ds_before: Dataset, ds_after: Dataset, lists: J.JudgeLists,
          out: Path | None = None) -> Path:
    out = out or after_dir / "compare.md"
    out.write_text(generate(before_dir, after_dir, ds_before, ds_after, lists), encoding="utf-8", newline="\n")
    return out


def sources(compare_md: Path) -> tuple[Path, Path] | None:
    first = compare_md.read_text(encoding="utf-8").split("\n", 1)[0]
    m = HEADER_RE.match(first)
    return (REPO / m.group(1), REPO / m.group(2)) if m else None
