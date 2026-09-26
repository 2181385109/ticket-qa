"""
提示词注入评测 CLI(docs/plans/llm-injection-plan.md;用法见同目录 README.md)。

  python tests/llm_security/run_eval.py plan [--k 5] [--holdout]     只算调用次数,不发请求
  python tests/llm_security/run_eval.py pilot                          试跑 5 次(真实调用)
  python tests/llm_security/run_eval.py run --phase phase1 [--resume DIR]   正式运行(真实调用,可断点续跑)
  python tests/llm_security/run_eval.py rejudge DIR [DIR ...]          用已录制的 raw.jsonl 重新生成 report.md(不发请求)
  python tests/llm_security/run_eval.py labels export|apply [--csv 文件] [--reviewer 名字]
  python tests/llm_security/run_eval.py labels export-priority DIR     精简审核表:⚠ 样本 + 对照组优先级判错的样本(不发请求)
  python tests/llm_security/run_eval.py models                         列出上游可用模型(1 次真实调用)
  python tests/llm_security/run_eval.py format-split DIR [DIR ...]     分类输出格式形态:恰好一个对象 / 夹带 / 读不出(不发请求)
  python tests/llm_security/run_eval.py compare BEFORE AFTER [--out F]  防御前 / 后两次运行的对比报告(不发请求;默认写 AFTER/compare.md)
  python tests/llm_security/run_eval.py rule-signal DIR                每条样本上关键词规则的结论分布(交叉校验替代阈值的依据;不发请求)
  python tests/llm_security/run_eval.py replay SOURCE --run-label v2-replay [--service-ref REF]
                                                                       回放评估:SOURCE 录到的模型输出经 WireMock 逐条回放给当前服务(不发真实请求);
                                                                       先逐字节验证请求一致,一致才出 report.md / compare.md。一条命令跑完:tools/replay.ps1
  python tests/llm_security/run_eval.py replay-check SOURCE REPLAY     只重算回放验证(不发请求,只读两个运行目录)
  python tests/llm_security/run_eval.py rerun-compare PHASE1 RERUN AFTER  基线复跑对比:第一阶段 / 复跑 / 防御后,只看攻击样本(不发请求)
  python tests/llm_security/run_eval.py run --phase holdout --run-label pre|post --service-ref REF   留出集(防御前后各跑一次)
                                                                       一条命令跑完前后两次 + 对比:tests/llm_security/tools/holdout_compare.ps1

真实调用的前提:环境变量 LLM_API_KEY 存在(本脚本只检查存在、不读值——key 由服务进程自己读;models 子命令除外,
它直接调上游,值只放进请求头,不打印不落盘);服务以 LLM_MODE=real 启动且 LLM_BASE_URL 指向本脚本起的录制代理。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from llmsec import compare as CMP            # noqa: E402
from llmsec import crosscheck as XC          # noqa: E402
from llmsec import dataset as dsmod          # noqa: E402
from llmsec import judge as J                # noqa: E402
from llmsec import replay as RP              # noqa: E402
from llmsec import rerun as RR               # noqa: E402
from llmsec import report as R               # noqa: E402
from llmsec import runner as RN              # noqa: E402

DEFAULT_UPSTREAM = os.environ.get("LLM_UPSTREAM_BASE_URL", "https://api.deepseek.com")
DEFAULT_PROXY_PORT = int(os.environ.get("LLM_PROXY_PORT", "18090"))
SERVICE_LLM_LINE = re.compile(r"LlmClient = 真实调用 baseUrl=(\S+) model=(\S+) timeout=(\d+)ms")


def _out(msg: str) -> None:
    print(msg, flush=True)


def load_samples(holdout: bool) -> tuple[dsmod.Dataset, list[dict], frozenset[str]]:
    """(判定用数据集, 本次要跑的样本, 只建单不取草稿的样本 id)。
    留出集:要跑的是留出样本 + 被 A/B 留出样本引用的基底对照——翻转口径(A/B 主口径)要把攻击第 r 轮和基底第 r 轮配对,
    基底必须在同一次运行、同一版服务上跑;基底只为配对,不取草稿"""
    ds = dsmod.load()
    if not holdout:
        return ds, ds.samples, frozenset()
    ho = dsmod.load_holdout()
    combined = dsmod.Dataset(controls=ds.controls, attacks=ds.attacks + ho)
    base_ids = sorted({s["base_id"] for s in ho if s.get("attack_class") in ("A", "B") and s.get("base_id")})
    bases = [combined.by_id[i] for i in base_ids if i in combined.by_id]
    return combined, ho + bases, frozenset(b["id"] for b in bases)


# ---------------------------------------------------------------------- plan

def attacks_only(samples: list[dict]) -> list[dict]:
    """--attacks-only:只保留攻击样本(基线复跑,作者 2026-09-26:不跑对照组)。
    代价:A/B 的翻转口径需要同轮基底对照,复跑里没有,只能报原口径(攻击输出对期望),报告里写明"""
    return [s for s in samples if s["group"] == "attack"]


def cmd_plan(args) -> int:
    _, samples, classify_only = load_samples(args.holdout)
    if getattr(args, "attacks_only", False):
        samples = attacks_only(samples)
    if not samples:
        _out("holdout.jsonl 为空:没有要跑的样本")
        return 0
    s = RN.plan_summary(samples, args.k, classify_only)
    for key, n in s.items():
        _out(f"{key}\t{n}")
    budget = RN.Budget()
    if args.holdout:
        _out(f"留出集要跑两次(防御前 + 防御后),合计 {2 * s['合计']}")
        _out(f"预算:已用 {budget.total} / 上限 {budget.limit},两次跑完后将为 {budget.total + 2 * s['合计']}")
        return 0
    if getattr(args, "attacks_only", False):
        _out(f"预算:已用 {budget.total} / 上限 {budget.limit},本次运行后将为 {budget.total + s['合计']}(只跑攻击样本,不含试跑)")
        return 0
    _out(f"试跑\t{len(RN.PILOT_TASKS)}")
    _out(f"预算:已用 {budget.total} / 上限 {budget.limit},本次正式运行后将为 {budget.total + s['合计']}")
    return 0


# ---------------------------------------------------------------------- 真实运行的公共部分

def _preflight(base_url: str) -> dict:
    """停止条件 1 的前置检查 + 服务健康 + 从服务日志读出真实生效的 LLM 配置"""
    if not os.environ.get("LLM_API_KEY"):
        raise RN.StopRun("停止条件 1:环境变量 LLM_API_KEY 不存在")
    import requests
    try:
        h = requests.get(base_url + "/actuator/health", timeout=10).json()
    except (requests.RequestException, ValueError) as e:
        raise RN.StopRun(f"服务不可用 {base_url}: {e}")
    if h.get("status") != "UP":
        raise RN.StopRun(f"服务健康检查不是 UP: {h.get('status')}")
    sys.path.insert(0, str(HERE.parent / "api"))
    from framework.config import load_config   # noqa: E402
    cfg = load_config()
    seen = {}
    if cfg.service_log_path and Path(cfg.service_log_path).exists():
        text = Path(cfg.service_log_path).read_text(encoding="utf-8", errors="replace")
        found = SERVICE_LLM_LINE.findall(text)
        if found:
            b, m, t = found[-1]
            seen = {"llm.real.base-url": b, "llm.real.model": m, "llm.timeout-ms": int(t),
                    "source": "服务日志最后一条 'LlmClient = 真实调用' 启动行"}
    return seen


def _service_config(args, seen: dict) -> dict:
    return {"llm.mode": "real", "llm.timeout-ms(声明)": args.declared_timeout_ms,
            "llm.circuit.failure-threshold(声明)": args.declared_circuit_threshold,
            "从服务日志读到": seen or "未找到启动行(服务日志路径见 tests/api/config/local.env SERVICE_LOG_PATH)"}


def _open_run_dir(args, phase: str, samples: list[dict], ds: dsmod.Dataset, tasks: list, seen: dict) -> Path:
    if args.resume:
        run_dir = Path(args.resume).resolve()
        meta = RN.read_meta(run_dir)
        if meta["dataset_text_sha256"] != ds.text_sha256():
            raise RN.StopRun("续跑的目录与当前数据集文本指纹不一致,拒绝续跑")
        if int(meta["k"]) != args.k:
            raise RN.StopRun(f"续跑的目录 k={meta['k']},本次 k={args.k},拒绝续跑")
        return run_dir
    label = f"-{args.run_label}" if getattr(args, "run_label", None) else ""
    run_dir = RN.REPORTS_DIR / f"{phase}{label}-{RN.utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    RN.write_meta(run_dir, {
        "phase": phase, "run_label": getattr(args, "run_label", None), "k": args.k,
        "dataset_text_sha256": ds.text_sha256(), "planned_tasks": len(tasks),
        "sample_ids": sorted(s["id"] for s in samples),
        "git": RN.git_state(), "upstream_base": args.upstream, "proxy": f"127.0.0.1:{args.proxy_port}",
        "service_config": _service_config(args, seen), "sessions": [],
        **({"service_ref": args.service_ref} if getattr(args, "service_ref", None) else {}),
        **({"attacks_only": True} if getattr(args, "attacks_only", False) else {}),
    })
    return run_dir


def _execute(args, run_dir: Path, samples: list[dict], tasks: list, seen: dict) -> int:
    from llmsec.proxy import RecordingProxy
    meta = RN.read_meta(run_dir)
    session = {"started_utc": RN.utc_stamp(), "git": RN.git_state(), "service_llm_config_seen": seen}
    meta["sessions"].append(session)
    RN.write_meta(run_dir, meta)
    proxy = RecordingProxy(args.upstream, port=args.proxy_port).start()
    _out(f"录制代理 {proxy.url} → {args.upstream};输出 {run_dir}")
    code = 0
    try:
        executor = RN.LiveExecutor(proxy, base_url=args.base_url)
        result = RN.Runner(run_dir, samples, tasks, executor, RN.Budget(), log=_out).run()
        session["result"] = result
        _out(f"完成:{result}")
    except RN.StopRun as e:
        session["stopped"] = str(e)
        _out(f"停止:{e}")
        code = 2
    finally:
        proxy.stop()
        session["ended_utc"] = RN.utc_stamp()
        meta = RN.read_meta(run_dir)
        meta["sessions"][-1] = session
        RN.write_meta(run_dir, meta)
    return code


# ---------------------------------------------------------------------- pilot / run

def cmd_pilot(args) -> int:
    ds, samples, _ = load_samples(False)
    try:
        seen = _preflight(args.base_url)
        args.resume = None
        run_dir = _open_run_dir(args, "pilot", samples, ds, list(RN.PILOT_TASKS), seen)
    except RN.StopRun as e:
        _out(f"停止:{e}")
        return 2
    code = _execute(args, run_dir, samples, list(RN.PILOT_TASKS), seen)
    problems = pilot_check(run_dir)
    for p in problems:
        _out(f"  试跑检查不通过:{p}")
    if not problems:
        _out("试跑检查通过")
    return code or (3 if problems else 0)


def pilot_check(run_dir: Path) -> list[str]:
    records = RN.read_raw(run_dir / "raw.jsonl")
    problems = []
    if len(records) != len(RN.PILOT_TASKS):
        problems.append(f"期望 {len(RN.PILOT_TASKS)} 条记录,实际 {len(records)}")
    for r in records:
        ups = r.get("upstream") or []
        if len(ups) != 1:
            problems.append(f"{r['key']}: 代理录到 {len(ups)} 次上游调用(应为 1;0 说明服务没指向代理)")
            continue
        u = ups[0]
        if u.get("status") != 200:
            problems.append(f"{r['key']}: 上游状态 {u.get('status')} {u.get('error_body') or u.get('error') or ''}")
        if not u.get("response_model"):
            problems.append(f"{r['key']}: 响应里没有 model 字段")
        if u.get("content") is None:
            problems.append(f"{r['key']}: 响应里没有 content")
        if not J.e2e_view(r)["valid"]:
            problems.append(f"{r['key']}: 端到端无效 {J.e2e_view(r)['reason']}")
        log = r.get("call_log") or {}
        if log.get("response_model") != u.get("response_model"):
            problems.append(f"{r['key']}: llm_call_log.response_model={log.get('response_model')} 与上游不一致")
    return problems


def cmd_run(args) -> int:
    ds, samples, classify_only = load_samples(args.phase == "holdout")
    if args.attacks_only:
        samples = attacks_only(samples)
    if not samples:
        _out("没有要跑的样本(holdout.jsonl 为空?)")
        return 0
    if args.phase == "holdout":
        errors = dsmod.validate(dsmod.Dataset(controls=ds.controls, attacks=ds.attacks))
        if errors:
            _out("留出集校验失败:\n  " + "\n  ".join(errors))
            return 2
        if args.run_label not in ("pre", "post"):
            _out("留出集运行必须带 --run-label pre(防御前的服务)或 post(防御后的服务)")
            return 2
    tasks = RN.plan_tasks(samples, args.k, classify_only)
    try:
        seen = _preflight(args.base_url)
        run_dir = _open_run_dir(args, args.phase, samples, ds, tasks, seen)
        RN.Budget().check(0)
    except RN.StopRun as e:
        _out(f"停止:{e}")
        return 2
    code = _execute(args, run_dir, samples, tasks, seen)
    if code == 0:
        rejudge_one(run_dir, ds)
    return code


# ---------------------------------------------------------------------- 离线

def rejudge_one(run_dir: Path, ds: dsmod.Dataset | None = None, data_dir: Path | None = None) -> Path:
    data_dir = data_dir or dsmod.DATA_DIR
    ds = ds or dsmod.load(data_dir)
    meta = RN.read_meta(run_dir)
    if meta.get("phase") == "holdout":
        ds = dsmod.Dataset(controls=ds.controls, attacks=ds.attacks + dsmod.load_holdout(data_dir))
    out = R.write(run_dir, ds, J.load_lists(data_dir))
    _out(f"已生成 {out}")
    return out


def cmd_compare(args) -> int:
    before, after = Path(args.before).resolve(), Path(args.after).resolve()
    out = CMP.write(before, after, _dataset_for(before), _dataset_for(after), J.load_lists(dsmod.DATA_DIR),
                    Path(args.out).resolve() if args.out else None)
    _out(f"已生成 {out}")
    return 0


def cmd_rejudge(args) -> int:
    for d in args.run_dirs:
        rejudge_one(Path(d).resolve())
    return 0


def _dataset_for(run_dir: Path, data_dir: Path | None = None) -> dsmod.Dataset:
    data_dir = data_dir or dsmod.DATA_DIR
    ds = dsmod.load(data_dir)
    if RN.read_meta(run_dir).get("phase") == "holdout":
        ds = dsmod.Dataset(controls=ds.controls, attacks=ds.attacks + dsmod.load_holdout(data_dir))
    return ds


def format_split(run_dir: Path, data_dir: Path | None = None) -> dict[str, int]:
    """ADR-024 修订 #3 的依据数字:分类场景模型原始输出按服务端 LlmJson 的规则归类(judge.classify_format),键为 组:形态"""
    ds = _dataset_for(run_dir, data_dir)
    meta, records, dups = R.load_run(run_dir)
    return R.compute(meta, records, ds, J.load_lists(data_dir or dsmod.DATA_DIR), dups)["calls"]["formats"]


def cmd_format_split(args) -> int:
    for d in args.run_dirs:
        split = format_split(Path(d).resolve())
        _out(f"{Path(d).name}")
        for key, n in split.items():
            _out(f"  {key}	{n}")
        by_fmt: dict[str, int] = {}
        for key, n in split.items():
            by_fmt[key.split(":")[1]] = by_fmt.get(key.split(":")[1], 0) + n
        _out("  合计 " + " ".join(f"{f}={by_fmt.get(f, 0)}" for f in ("single", "mixed", "none")))
    return 0


def cmd_rule_signal(args) -> int:
    """ADR-024 修订 #4 的依据:规则给 OTHER/P2(一个类别都没命中)的样本上,"只在规则命中类别时才判优先级冲突"永远不触发"""
    run_dir = Path(args.run_dir).resolve()
    _, records, _ = R.load_run(run_dir)
    sig = XC.rule_signal(_dataset_for(run_dir), records)
    if not sig:
        _out("这批记录里没有规则结论(llm_call_log.rule_category 是第二阶段才加的字段)")
        return 0
    _out(f"{run_dir.name}  样本数 = 分类第 0 轮的规则结论(规则确定性,每轮相同)")
    for g, c in sig.items():
        _out(f"  {g}	合计 {sum(c.values())}	" + "  ".join(f"{k}={n}" for k, n in c.items()))
    return 0


# ---------------------------------------------------------------------- 回放(v2 评估,ADR-024 修订 #4)

def _replay_preflight(base_url: str, proxy_port: int) -> dict:
    """服务必须以真实模式启动、LLM_BASE_URL 指向本脚本的录制代理——否则请求到不了回放桩。不检查 LLM_API_KEY:回放不打上游"""
    import requests
    try:
        h = requests.get(base_url + "/actuator/health", timeout=10).json()
    except (requests.RequestException, ValueError) as e:
        raise RN.StopRun(f"服务不可用 {base_url}: {e}")
    if h.get("status") != "UP":
        raise RN.StopRun(f"服务健康检查不是 UP: {h.get('status')}")
    sys.path.insert(0, str(HERE.parent / "api"))
    from framework.config import load_config   # noqa: E402
    cfg = load_config()
    found = []
    if cfg.service_log_path and Path(cfg.service_log_path).exists():
        found = SERVICE_LLM_LINE.findall(Path(cfg.service_log_path).read_text(encoding="utf-8", errors="replace"))
    if not found:
        raise RN.StopRun("服务日志里没有 'LlmClient = 真实调用' 启动行:服务不是真实模式,回放桩收不到请求")
    b, m, t = found[-1]
    if not b.rstrip("/").endswith(f":{proxy_port}"):
        raise RN.StopRun(f"服务的 LLM baseUrl={b},没有指向录制代理 127.0.0.1:{proxy_port}")
    return {"llm.real.base-url": b, "llm.real.model": m, "llm.timeout-ms": int(t),
            "source": "服务日志最后一条 'LlmClient = 真实调用' 启动行"}


def replay_check(source_dir: Path, replay_dir: Path) -> tuple[bool, Path]:
    """验证 + 写 replay_check.md(确定性,可由已提交的两个运行目录逐字节重算)"""
    meta = RN.read_meta(replay_dir)
    _, src_records, _ = R.load_run(source_dir)
    _, rep_records, _ = R.load_run(replay_dir)
    keys = meta["replay"]["task_keys"]
    diffs = RP.compare_requests(src_records, rep_records, keys)
    misaligned = RP.check_alignment(src_records, rep_records, keys)
    out = replay_dir / "replay_check.md"
    out.write_text(RP.render_check(CMP._rel(source_dir), CMP._rel(replay_dir), len(keys), diffs, misaligned),
                   encoding="utf-8", newline="\n")
    return not diffs and not misaligned, out


def cmd_replay(args) -> int:
    from llmsec.proxy import RecordingProxy
    source = Path(args.source).resolve()
    smeta = RN.read_meta(source)
    ds = _dataset_for(source)
    if smeta["dataset_text_sha256"] != ds.text_sha256():
        _out("源运行的数据集文本指纹与当前数据集不一致,拒绝回放")
        return 2
    samples = [ds.by_id[i] for i in smeta["sample_ids"]]
    k = int(smeta["k"])
    tasks = RN.plan_tasks(samples, k)
    try:
        _, src_records, _ = R.load_run(source)
        calls = RP.source_calls(src_records, tasks)
        seen = _replay_preflight(args.base_url, args.proxy_port)
    except (RP.ReplayError, RN.StopRun) as e:
        _out(f"停止:{e}")
        return 2
    label = args.run_label or "v2-replay"
    run_dir = RN.REPORTS_DIR / f"{smeta['phase']}-{label}-{RN.utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=False)
    wm = args.wiremock.rstrip("/")
    RN.write_meta(run_dir, {
        "phase": smeta["phase"], "run_label": label, "k": k, "dataset_text_sha256": ds.text_sha256(),
        "planned_tasks": len(tasks), "sample_ids": smeta["sample_ids"], "git": RN.git_state(),
        "upstream_base": wm + RP.PREFIX, "proxy": f"127.0.0.1:{args.proxy_port}",
        "service_config": {"llm.mode": "real(上游 = WireMock 回放桩)", "从服务日志读到": seen},
        "replay": {"source": CMP._rel(source), "method": RP.METHOD_NOTE, "scenario": RP.SCENARIO,
                   "stubs": len(calls), "task_keys": [t.key for t in tasks]},
        "sessions": [], **({"service_ref": args.service_ref} if args.service_ref else {}),
    })
    admin = RP.WireMockAdmin(wm)
    admin.load(RP.build_stubs(calls))
    _out(f"已加载 {len(calls)} 个回放桩(场景 {RP.SCENARIO}),源运行 {source.name};输出 {run_dir}")
    meta = RN.read_meta(run_dir)
    session = {"started_utc": RN.utc_stamp(), "git": RN.git_state(), "service_llm_config_seen": seen}
    proxy = RecordingProxy(wm + RP.PREFIX, port=args.proxy_port).start()
    code = 0
    try:
        executor = RN.LiveExecutor(proxy, base_url=args.base_url)
        session["result"] = RN.Runner(run_dir, samples, tasks, executor, RP.NoBudget(), log=_out).run()
        session["wiremock_final_state"] = admin.state()
        _out(f"完成:{session['result']};场景终态 {session['wiremock_final_state']}(应为 step-{len(calls)})")
    except RN.StopRun as e:
        session["stopped"] = str(e)
        _out(f"停止:{e}")
        code = 2
    finally:
        proxy.stop()
        admin.remove()
        session["ended_utc"] = RN.utc_stamp()
        meta["sessions"].append(session)
        RN.write_meta(run_dir, meta)
    if code:
        return code
    ok, check = replay_check(source, run_dir)
    _out(f"回放验证:{'一致' if ok else '不一致'} → {check}")
    if not ok:
        _out("请求与源运行不一致:v1 的模型输出对这版服务不成立,不生成 report.md / compare.md(计划:不一致则停下,报告差异)")
        return 4
    rejudge_one(run_dir, ds)
    out = CMP.write(source, run_dir, ds, ds, J.load_lists(dsmod.DATA_DIR))
    _out(f"已生成 {out}")
    return 0


def cmd_rerun_compare(args) -> int:
    p1, rr, af = (Path(x).resolve() for x in (args.phase1, args.rerun, args.after))
    out = RR.write(p1, rr, af, dsmod.load(), J.load_lists(dsmod.DATA_DIR))
    _out(f"已生成 {out}")
    return 0


def cmd_replay_check(args) -> int:
    ok, out = replay_check(Path(args.source).resolve(), Path(args.replay).resolve())
    _out(f"回放验证:{'一致' if ok else '不一致'} → {out}")
    return 0 if ok else 4


PRIORITY_CSV = "label_review_priority.csv"


def export_priority(run_dir: Path, out: Path, data_dir: Path | None = None) -> int:
    """精简审核表(M5.5):⚠ 样本 + 该运行里对照组优先级判错的样本。只读已录制的 raw,不发请求"""
    data_dir = data_dir or dsmod.DATA_DIR
    ds = dsmod.load(data_dir)
    meta, records, dups = R.load_run(run_dir)
    st = R.compute(meta, records, ds, J.load_lists(data_dir), dups)
    return dsmod.export_review(ds, out, only=st["review"]["priority_rows"])


def cmd_labels(args) -> int:
    ds = dsmod.load()
    if args.action == "export-priority":
        if not args.run_dir:
            _out("export-priority 需要运行目录:labels export-priority tests/llm_security/reports/phase1-<UTC>")
            return 2
        path = Path(args.csv) if args.csv else dsmod.DATA_DIR / PRIORITY_CSV
        n = export_priority(Path(args.run_dir).resolve(), path)
        _out(f"已导出 {n} 行 → {path}")
        return 0
    path = Path(args.csv) if args.csv else dsmod.DATA_DIR / "label_review.csv"
    if args.action == "export":
        n = dsmod.export_review(ds, path)
        _out(f"已导出 {n} 行 → {path}")
        return 0
    try:
        stats = dsmod.apply_review(ds, path, reviewer=args.reviewer)
    except ValueError as e:
        _out(str(e))
        return 2
    dsmod.save(ds)
    _out(f"已回写:{stats}。接着对每个运行目录执行 rejudge 重新生成报告。")
    return 0


def cmd_models(args) -> int:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        _out("停止条件 1:环境变量 LLM_API_KEY 不存在")
        return 2
    import requests
    budget = RN.Budget()
    budget.check(1)
    r = requests.get(args.upstream.rstrip("/") + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    budget.add("models", 1)
    if r.status_code in (401, 403):
        _out(f"停止条件 1:鉴权失败 HTTP {r.status_code}")
        return 2
    ids = sorted(m.get("id") for m in (r.json().get("data") or []))
    out = RN.REPORTS_DIR / f"models-{RN.utc_stamp()}.json"
    out.write_text(json.dumps({"upstream": args.upstream, "status": r.status_code, "ids": ids}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    _out(f"HTTP {r.status_code} 模型:{ids} → {out}")
    return 0


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan")
    sp.add_argument("--k", type=int, default=5)
    sp.add_argument("--holdout", action="store_true")
    sp.add_argument("--attacks-only", action="store_true", help="只算攻击样本(基线复跑)")
    sp.set_defaults(func=cmd_plan)

    def live(sp_):
        sp_.add_argument("--upstream", default=DEFAULT_UPSTREAM)
        sp_.add_argument("--proxy-port", type=int, default=DEFAULT_PROXY_PORT)
        sp_.add_argument("--base-url", default=None, help="服务地址,默认取 tests/api/config/local.env")
        sp_.add_argument("--declared-timeout-ms", type=int, default=30000)
        sp_.add_argument("--declared-circuit-threshold", type=int, default=100000)

    sp = sub.add_parser("pilot")
    live(sp)
    sp.set_defaults(func=cmd_pilot, k=1)

    sp = sub.add_parser("run")
    live(sp)
    sp.add_argument("--phase", required=True, choices=("phase1", "phase2", "holdout"))
    sp.add_argument("--run-label", default=None, help="第二阶段 v1 / v2(计划 §2-8)")
    sp.add_argument("--k", type=int, default=5)
    sp.add_argument("--resume", default=None, help="断点续跑:已有的运行目录")
    sp.add_argument("--service-ref", default=None, help="本次打的是哪一版服务代码(tag / commit),写进 meta 与报告;留出集前后对比必填")
    sp.add_argument("--attacks-only", action="store_true", help="只跑攻击样本(基线复跑:不跑对照组,A/B 只能报原口径)")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("compare")
    sp.add_argument("before")
    sp.add_argument("after")
    sp.add_argument("--out", default=None)
    sp.set_defaults(func=cmd_compare)

    sp = sub.add_parser("rejudge")
    sp.add_argument("run_dirs", nargs="+")
    sp.set_defaults(func=cmd_rejudge)

    sp = sub.add_parser("labels")
    sp.add_argument("action", choices=("export", "apply", "export-priority"))
    sp.add_argument("run_dir", nargs="?", default=None, help="export-priority 用:已录制的运行目录")
    sp.add_argument("--csv", default=None)
    sp.add_argument("--reviewer", default="作者")
    sp.set_defaults(func=cmd_labels)

    sp = sub.add_parser("format-split")
    sp.add_argument("run_dirs", nargs="+")
    sp.set_defaults(func=cmd_format_split)

    sp = sub.add_parser("replay")
    live(sp)
    sp.add_argument("source", help="源运行目录(其模型输出被回放)")
    sp.add_argument("--run-label", default="v2-replay")
    sp.add_argument("--service-ref", default=None, help="本次回放打的是哪一版服务代码,写进 meta 与报告")
    sp.add_argument("--wiremock", default=os.environ.get("WIREMOCK_URL", "http://localhost:8089"))
    sp.set_defaults(func=cmd_replay)

    sp = sub.add_parser("rerun-compare")
    sp.add_argument("phase1")
    sp.add_argument("rerun")
    sp.add_argument("after")
    sp.set_defaults(func=cmd_rerun_compare)

    sp = sub.add_parser("replay-check")
    sp.add_argument("source")
    sp.add_argument("replay")
    sp.set_defaults(func=cmd_replay_check)

    sp = sub.add_parser("rule-signal")
    sp.add_argument("run_dir")
    sp.set_defaults(func=cmd_rule_signal)

    sp = sub.add_parser("models")
    sp.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    sp.set_defaults(func=cmd_models)

    args = p.parse_args(argv)
    if getattr(args, "base_url", "x") is None:
        sys.path.insert(0, str(HERE.parent / "api"))
        from framework.config import load_config   # noqa: E402
        args.base_url = load_config().base_url
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
