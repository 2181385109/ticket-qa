"""
评测执行:把样本变成对服务的调用,每次调用落一行 raw.jsonl。

- 任务:(样本, 场景, 第几次)。分类任务 = 建一张工单(服务内部调一次 LLM 分类);草稿任务 = 对该样本第 0 次建出的工单取一次草稿。
  A/B 与对照:每轮建单;C/D:只在第 0 轮建单一次,之后每轮在同一张单上取草稿;对照每轮也取草稿。
- 顺序按轮次交错:第 0 轮所有样本 → 第 1 轮所有样本 ……(供应商侧的时段波动不集中落在少数样本上)。
- 断点续跑:raw.jsonl 按 key = 样本|场景|次数 去重,已有的 key 不再执行。
- 停止条件(计划 §2-9):上游连续失败 3 次 → 这 3 条移入 failures.jsonl(不进 raw,续跑时会重试)→ 等 60 s 重试这 3 个任务 →
  仍连续失败 3 次则停;401/403 立即停;累计真实调用超过预算立即停。
- 每条记录只存观测(接口响应、llm_call_log、代理录到的上游调用),不存判定——判定在 report.py 里离线算。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

HERE = Path(__file__).resolve().parent.parent            # tests/llm_security
REPO = HERE.parent.parent
REPORTS_DIR = HERE / "reports"
BUDGET_FILE = REPORTS_DIR / "call_budget.json"
BUDGET_LIMIT = 1300
FAILURE_STREAK_LIMIT = 3
RETRY_WAIT_SECONDS = 60


class StopRun(Exception):
    """硬性停止条件触发。message 写清是哪一条"""


@dataclass(frozen=True)
class Task:
    sample_id: str
    scene: str          # classify | draft
    repeat: int

    @property
    def key(self) -> str:
        return f"{self.sample_id}|{self.scene}|{self.repeat}"


# ---------------------------------------------------------------------- 任务规划

def needs_classify(sample: dict[str, Any], repeat: int) -> bool:
    if sample["group"] == "control" or sample["attack_class"] in ("A", "B"):
        return True
    return repeat == 0          # C/D 只建一次单


def needs_draft(sample: dict[str, Any]) -> bool:
    return sample["group"] == "control" or sample["attack_class"] in ("C", "D")


def plan_tasks(samples: Iterable[dict[str, Any]], k: int) -> list[Task]:
    ordered = sorted(samples, key=lambda s: s["id"])
    tasks: list[Task] = []
    for r in range(k):
        for s in ordered:
            if needs_classify(s, r):
                tasks.append(Task(s["id"], "classify", r))
            if needs_draft(s):
                tasks.append(Task(s["id"], "draft", r))
    return tasks


def plan_summary(samples: list[dict[str, Any]], k: int) -> dict[str, int]:
    """--plan 的输出:每一项都能从数据集和 k 算出来,不发请求。一个任务 = 一次上游调用"""
    by_id = {s["id"]: s for s in samples}
    out = {"A/B 分类": 0, "对照分类": 0, "C/D 建单": 0, "C/D 草稿": 0, "对照草稿": 0}
    for t in plan_tasks(samples, k):
        s = by_id[t.sample_id]
        if t.scene == "classify":
            out["对照分类" if s["group"] == "control" else ("A/B 分类" if s["attack_class"] in ("A", "B") else "C/D 建单")] += 1
        else:
            out["对照草稿" if s["group"] == "control" else "C/D 草稿"] += 1
    out["合计"] = sum(out.values())
    return out


PILOT_TASKS = (Task("N-001", "classify", 0), Task("N-001", "draft", 0), Task("A-001", "classify", 0),
               Task("C-001", "classify", 0), Task("C-001", "draft", 0))


# ---------------------------------------------------------------------- 预算

class Budget:
    """真实上游调用累计计数,跨运行、跨会话持久化(reports/call_budget.json,随仓库提交)"""

    def __init__(self, path: Path = BUDGET_FILE, limit: int = BUDGET_LIMIT):
        self.path, self.limit = path, limit
        self.state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"limit": limit, "total": 0, "runs": {}}

    @property
    def total(self) -> int:
        return self.state["total"]

    def check(self, upcoming: int = 1) -> None:
        if self.total + upcoming > self.limit:
            raise StopRun(f"停止条件 3:真实调用累计 {self.total} 次,再调 {upcoming} 次会超过上限 {self.limit}")

    def add(self, run: str, n: int) -> None:
        if n <= 0:
            return
        self.state["total"] += n
        self.state["runs"][run] = self.state["runs"].get(run, 0) + n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------- raw 文件

def read_raw(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_jsonl(path: Path, rec: dict[str, Any]) -> None:
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def is_upstream_failure(rec: dict[str, Any]) -> bool:
    """这次调用是不是"上游不可用"——代理没收到请求、上游非 200、连不上、或服务本身没响应"""
    api = rec.get("api") or {}
    if api.get("status") is None:
        return True
    ups = rec.get("upstream") or []
    if not ups:
        return rec.get("skipped") is None
    last = ups[-1]
    return last.get("status") != 200


def is_auth_failure(rec: dict[str, Any]) -> bool:
    return any(u.get("status") in (401, 403) for u in rec.get("upstream") or [])


# ---------------------------------------------------------------------- 执行

Executor = Callable[[Task, dict[str, Any], "int | None"], dict[str, Any]]


class Runner:
    def __init__(self, run_dir: Path, samples: list[dict[str, Any]], tasks: list[Task], executor: Executor,
                 budget: Budget, sleep: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print):
        self.run_dir = run_dir
        self.raw_path = run_dir / "raw.jsonl"
        self.fail_path = run_dir / "failures.jsonl"
        self.by_id = {s["id"]: s for s in samples}
        self.tasks = tasks
        self.executor = executor
        self.budget = budget
        self.sleep = sleep
        self.log = log

    def _ticket_for(self, sample_id: str, done: dict[str, dict[str, Any]]) -> int | None:
        rec = done.get(f"{sample_id}|classify|0")
        return rec.get("ticket_id") if rec else None

    def run(self) -> dict[str, int]:
        done = {r["key"]: r for r in read_raw(self.raw_path)}
        pending = [t for t in self.tasks if t.key not in done]
        self.log(f"任务 {len(self.tasks)},已完成 {len(self.tasks) - len(pending)},本次待执行 {len(pending)}")
        streak: list[tuple[Task, dict[str, Any]]] = []
        retried = False
        executed = 0
        queue = list(pending)
        while queue:
            task = queue.pop(0)
            if task.key in done:
                continue
            ticket_id = None
            if task.scene == "draft":
                # 上游失败时服务会降级到规则、工单照样建出来,所以连续失败缓冲里的建单记录也能提供工单
                ticket_id = self._ticket_for(task.sample_id, {**done, **{t.key: r for t, r in streak}})
                if ticket_id is None:
                    self.log(f"  跳过 {task.key}:该样本第 0 次建单没有得到工单(不落盘,续跑时再试)")
                    continue
            self.budget.check(1)
            rec = self.executor(task, self.by_id[task.sample_id], ticket_id)
            self.budget.add(self.run_dir.name, len(rec.get("upstream") or []))
            executed += 1
            if is_auth_failure(rec):
                append_jsonl(self.fail_path, rec)
                raise StopRun("停止条件 1:上游鉴权失败(401/403)——检查 LLM_API_KEY")
            if rec.get("skipped") is None and is_upstream_failure(rec):
                streak.append((task, rec))
                self.log(f"  上游失败 {task.key}(连续 {len(streak)})")
                if len(streak) >= FAILURE_STREAK_LIMIT:
                    for _, r in streak:
                        append_jsonl(self.fail_path, r)
                    if retried:
                        raise StopRun(f"停止条件 2:上游连续失败 {FAILURE_STREAK_LIMIT} 次,间隔 {RETRY_WAIT_SECONDS} s 重试一轮后仍失败")
                    self.log(f"  连续失败 {FAILURE_STREAK_LIMIT} 次,等 {RETRY_WAIT_SECONDS} s 后重试这一轮")
                    self.sleep(RETRY_WAIT_SECONDS)
                    queue[:0] = [t for t, _ in streak]
                    streak, retried = [], True
                continue
            # 成功(或跳过):之前零星的失败是真实结果,落进 raw
            for t, r in streak:
                append_jsonl(self.raw_path, r)
                done[t.key] = r
            streak, retried = [], False
            append_jsonl(self.raw_path, rec)
            done[task.key] = rec
            if executed and executed % 20 == 0:
                self.log(f"  进度 {len(done)}/{len(self.tasks)},累计真实调用 {self.budget.total}")
        for t, r in streak:            # 结尾残留的零星失败(不足 3 次)照实落盘
            append_jsonl(self.raw_path, r)
            done[t.key] = r
        return {"total": len(self.tasks), "done": len(done), "executed": executed}


# ---------------------------------------------------------------------- 真实环境执行器

class LiveExecutor:
    """对真实服务发请求;服务的 LLM_BASE_URL 必须指向本进程里的录制代理"""

    def __init__(self, proxy, base_url: str | None = None, user_id: int = 1, timeout: float = 180.0):
        import sys
        sys.path.insert(0, str(HERE.parent / "api"))
        from framework.config import load_config   # noqa: E402  复用接口自动化的环境配置(地址、MySQL)
        from framework.db import Db                 # noqa: E402
        import requests

        cfg = load_config()
        self.base_url = (base_url or cfg.base_url).rstrip("/")
        self.db = Db(cfg)
        self.proxy = proxy
        self.session = requests.Session()
        self.headers = {"X-User-Id": str(user_id), "Content-Type": "application/json; charset=utf-8"}
        self.timeout = timeout

    def _post(self, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        import requests
        t0 = time.perf_counter()
        try:
            r = self.session.post(self.base_url + path, headers=self.headers, timeout=self.timeout,
                                  data=json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None)
        except requests.RequestException as e:
            return {"status": None, "error": f"{type(e).__name__}: {str(e)[:300]}",
                    "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
        out: dict[str, Any] = {"status": r.status_code, "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
        try:
            env = r.json()
            out.update(code=env.get("code"), message=env.get("message"), data=env.get("data"), trace_id=env.get("traceId"))
        except ValueError:
            out["text"] = r.text[:2000]
        return out

    def _call_log(self, ticket_id: int | None, scene: str) -> dict[str, Any] | None:
        if ticket_id is None:
            return None
        row = self.db.one("SELECT * FROM llm_call_log WHERE ticket_id=%s AND scene=%s ORDER BY id DESC LIMIT 1",
                          (ticket_id, scene))
        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()} if row else None

    def __call__(self, task: Task, sample: dict[str, Any], ticket_id: int | None) -> dict[str, Any]:
        self.proxy.drain()
        started = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if task.scene == "classify":
            api = self._post("/api/tickets", {"title": sample["title"], "content": sample["content"], "customerId": 1001})
            tid = (api.get("data") or {}).get("id") if isinstance(api.get("data"), dict) else None
            log_row = self._call_log(tid, "CLASSIFY")
        else:
            api = self._post(f"/api/tickets/{ticket_id}/reply-draft", None)
            tid = ticket_id
            log_row = self._call_log(tid, "DRAFT_REPLY")
        return {"key": task.key, "sample_id": task.sample_id, "scene": task.scene, "repeat": task.repeat,
                "t_utc": started, "ticket_id": tid, "api": api, "call_log": log_row, "upstream": self.proxy.drain()}


# ---------------------------------------------------------------------- meta

def git_state() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    return {"commit": run("rev-parse", "HEAD"), "dirty_files": len([l for l in run("status", "--porcelain").splitlines() if l])}


def utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_meta(run_dir: Path, meta: dict[str, Any]) -> None:
    (run_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_meta(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
