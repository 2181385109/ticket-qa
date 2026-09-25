"""
提示词注入评测 CLI(docs/plans/llm-injection-plan.md;用法见同目录 README.md)。

  python tests/llm_security/run_eval.py plan [--k 5] [--holdout]     只算调用次数,不发请求
  python tests/llm_security/run_eval.py pilot                          试跑 5 次(真实调用)
  python tests/llm_security/run_eval.py run --phase phase1 [--resume DIR]   正式运行(真实调用,可断点续跑)
  python tests/llm_security/run_eval.py rejudge DIR [DIR ...]          用已录制的 raw.jsonl 重新生成 report.md(不发请求)
  python tests/llm_security/run_eval.py labels export|apply [--reviewer 名字]
  python tests/llm_security/run_eval.py models                         列出上游可用模型(1 次真实调用)

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

from llmsec import dataset as dsmod          # noqa: E402
from llmsec import judge as J                # noqa: E402
from llmsec import report as R               # noqa: E402
from llmsec import runner as RN              # noqa: E402

DEFAULT_UPSTREAM = os.environ.get("LLM_UPSTREAM_BASE_URL", "https://api.deepseek.com")
DEFAULT_PROXY_PORT = int(os.environ.get("LLM_PROXY_PORT", "18090"))
SERVICE_LLM_LINE = re.compile(r"LlmClient = 真实调用 baseUrl=(\S+) model=(\S+) timeout=(\d+)ms")


def _out(msg: str) -> None:
    print(msg, flush=True)


def load_samples(holdout: bool) -> tuple[dsmod.Dataset, list[dict]]:
    ds = dsmod.load()
    if not holdout:
        return ds, ds.samples
    ho = dsmod.load_holdout()
    return dsmod.Dataset(controls=ds.controls, attacks=ds.attacks + ho), ho


# ---------------------------------------------------------------------- plan

def cmd_plan(args) -> int:
    _, samples = load_samples(args.holdout)
    if not samples:
        _out("holdout.jsonl 为空:没有要跑的样本")
        return 0
    s = RN.plan_summary(samples, args.k)
    for key, n in s.items():
        _out(f"{key}\t{n}")
    budget = RN.Budget()
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
    ds, samples = load_samples(False)
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
    ds, samples = load_samples(args.phase == "holdout")
    if not samples:
        _out("没有要跑的样本(holdout.jsonl 为空?)")
        return 0
    if args.phase == "holdout":
        errors = dsmod.validate(dsmod.Dataset(controls=ds.controls, attacks=ds.attacks))
        if errors:
            _out("留出集校验失败:\n  " + "\n  ".join(errors))
            return 2
    tasks = RN.plan_tasks(samples, args.k)
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


def cmd_rejudge(args) -> int:
    for d in args.run_dirs:
        rejudge_one(Path(d).resolve())
    return 0


def cmd_labels(args) -> int:
    ds = dsmod.load()
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
                   encoding="utf-8")
    _out(f"HTTP {r.status_code} 模型:{ids} → {out}")
    return 0


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plan")
    sp.add_argument("--k", type=int, default=5)
    sp.add_argument("--holdout", action="store_true")
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
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("rejudge")
    sp.add_argument("run_dirs", nargs="+")
    sp.set_defaults(func=cmd_rejudge)

    sp = sub.add_parser("labels")
    sp.add_argument("action", choices=("export", "apply"))
    sp.add_argument("--csv", default=None)
    sp.add_argument("--reviewer", default="作者")
    sp.set_defaults(func=cmd_labels)

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
