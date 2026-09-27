"""
回放评估(v2,ADR-024 修订 #4):把一次已录制运行(v1)里模型的原始输出,经 WireMock 逐条回放给另一版服务(v2),不发任何真实请求。

前提与验证(缺一不可):
  v2 只改了模型输出之后的确定性逻辑,**模型的输入应当不变**。这不能假设,要验证——回放运行里 v2 发出的每一个请求
  (model / temperature / max_tokens / response_format / 全部 messages 的 role 与 content),必须与源运行同一个任务 key 录到的请求逐字节一致。
  不一致就说明 v2 改变了模型输入,v1 的模型输出对它不成立:不出结果报告,只出差异报告。

回放怎么对上号(为什么用一个全局场景,而不是按请求体匹配):
  runner 串行执行、任务顺序由 plan_tasks 确定(按轮次交错),每个任务恰好一次上游调用——源运行 538 条记录每条恰好 1 次(replay 前检查)。
  所以第 i 个上游请求就是第 i 个任务的请求。WireMock 场景 `llm-replay` 从 Started 走到 step-1、step-2……,第 i 个桩只在状态 step-i 时匹配,
  返回第 i 个任务在源运行里录到的模型输出。桩**不按请求体匹配**:请求体不一致时照样返回(否则服务会降级、打乱后面的顺序,差异也看不全),
  一致与否在跑完后由 compare_requests 逐条判定,判定不通过则整个回放作废。另外 check_alignment 核对每条回放记录拿到的 content 与源运行同 key 的逐字节相同,
  证明没有错位、也没有被 WireMock 改写(WireMock 开着全局响应模板,响应体用 base64Body 给出,不经模板引擎)。

报告方法说明(写进 meta 与报告):v2 仅改变输出端的确定性逻辑,模型输入不变(已逐条验证),因此复用 v1 录制的模型输出;模型的随机性没有重新采样。
"""
from __future__ import annotations

import base64
import difflib
import json
import uuid
from pathlib import Path
from typing import Any

from .runner import Task

SCENARIO = "llm-replay"
PREFIX = "/llm-replay"
REQUEST_FIELDS = ("model", "temperature", "max_tokens", "response_format")
METHOD_NOTE = ("v2 仅改变输出端的确定性逻辑,模型输入不变,因此复用 v1 录制的模型输出;模型的随机性没有重新采样。"
               "模型输入不变不是假设:回放运行里服务发出的每个请求都与源运行同一任务录到的请求逐字节比对过(replay_check.md)。")
_NS = uuid.UUID("7f1c1f0e-6a55-4f59-9d53-2b8b8d3f6a01")


class ReplayError(Exception):
    """源运行不满足回放前提(不是恰好一次上游调用、上游非 200、缺记录)"""


class NoBudget:
    """回放不打上游,不计入真实调用预算(reports/call_budget.json 不动)"""

    total = 0
    limit = 0

    def check(self, upcoming: int = 1) -> None:
        return None

    def add(self, run: str, n: int) -> None:
        return None


# ---------------------------------------------------------------------- 源运行 → 按任务顺序的上游调用

def source_calls(records: list[dict[str, Any]], tasks: list[Task]) -> list[tuple[str, dict[str, Any]]]:
    """[(任务 key, 源运行录到的那次上游调用)],顺序 = 任务顺序。任何一条不满足前提都拒绝回放"""
    by_key = {r["key"]: r for r in records}
    out = []
    problems = []
    for t in tasks:
        r = by_key.get(t.key)
        if r is None:
            problems.append(f"{t.key}: 源运行里没有这条记录")
            continue
        ups = r.get("upstream") or []
        if len(ups) != 1:
            problems.append(f"{t.key}: 源运行录到 {len(ups)} 次上游调用(回放要求恰好 1 次)")
            continue
        if ups[0].get("status") != 200 or ups[0].get("content") is None:
            problems.append(f"{t.key}: 源运行上游状态 {ups[0].get('status')},没有可回放的输出")
            continue
        out.append((t.key, ups[0]))
    if problems:
        raise ReplayError("源运行不满足回放前提:\n  " + "\n  ".join(problems[:20]) + (f"\n  …共 {len(problems)} 条" if len(problems) > 20 else ""))
    return out


def response_body(key: str, up: dict[str, Any]) -> dict[str, Any]:
    """OpenAI 兼容响应:服务读的字段(choices[0].message.content、model)和代理记录的字段(system_fingerprint、usage、finish_reason)都按源运行原样给出"""
    return {"id": f"replay-{key}", "object": "chat.completion", "model": up.get("response_model"),
            "system_fingerprint": up.get("system_fingerprint"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": up.get("content")},
                         "finish_reason": up.get("finish_reason")}],
            "usage": up.get("usage")}


def build_stubs(calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    stubs = []
    for i, (key, up) in enumerate(calls):
        body = json.dumps(response_body(key, up), ensure_ascii=False).encode("utf-8")
        stubs.append({
            "id": str(uuid.uuid5(_NS, f"{i}|{key}")),
            "name": f"replay {i + 1}/{len(calls)} {key}",
            "priority": 1,
            "scenarioName": SCENARIO,
            "requiredScenarioState": "Started" if i == 0 else f"step-{i}",
            "newScenarioState": f"step-{i + 1}",
            "request": {"method": "POST", "url": f"{PREFIX}/chat/completions"},
            "response": {"status": 200, "headers": {"Content-Type": "application/json; charset=utf-8"},
                         "base64Body": base64.b64encode(body).decode("ascii")},
            "metadata": {"llmReplay": {"step": i, "key": key}},
        })
    return stubs


# ---------------------------------------------------------------------- WireMock 管理接口

class WireMockAdmin:
    def __init__(self, base_url: str, session=None):
        import requests
        self.base = base_url.rstrip("/")
        self.s = session or requests.Session()

    def load(self, stubs: list[dict[str, Any]]) -> None:
        self.remove()
        r = self.s.post(self.base + "/__admin/mappings/import", timeout=60,
                        json={"mappings": stubs, "importOptions": {"duplicatePolicy": "OVERWRITE", "deleteAllNotInImport": False}})
        r.raise_for_status()
        r = self.s.put(self.base + f"/__admin/scenarios/{SCENARIO}/state", json={"state": "Started"}, timeout=10)
        r.raise_for_status()

    def state(self) -> str | None:
        r = self.s.get(self.base + "/__admin/scenarios", timeout=10)
        r.raise_for_status()
        for sc in r.json().get("scenarios") or []:
            if sc.get("name") == SCENARIO:
                return sc.get("state")
        return None

    def remove(self) -> None:
        """只删回放桩(按 metadata),挡板模式用的桩不动"""
        r = self.s.post(self.base + "/__admin/mappings/remove-by-metadata", timeout=30,
                        json={"matchesJsonPath": "$.llmReplay"})
        r.raise_for_status()


# ---------------------------------------------------------------------- 验证

def _request(rec: dict[str, Any]) -> dict[str, Any] | None:
    ups = rec.get("upstream") or []
    return (ups[0].get("request") or {}) if len(ups) == 1 else None


def _text_diff(a: str, b: str) -> list[str]:
    return [line for line in difflib.unified_diff(a.splitlines(), b.splitlines(), "源运行", "回放运行", lineterm="", n=0)
            if not line.startswith(("---", "+++", "@@"))]


def request_diffs(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, str]]:
    """一对请求的差异([] = 逐字节一致)。messages 按位置比对 role 与 content 的 UTF-8 字节。
    回放验证(跑完后)与混合回放代理(请求到达时决定回放还是重新采样)共用这一个判据"""
    diffs = []
    for f in REQUEST_FIELDS:
        if a.get(f) != b.get(f):
            diffs.append({"field": f, "detail": f"{a.get(f)!r} → {b.get(f)!r}"})
    ma, mb = a.get("messages") or [], b.get("messages") or []
    if len(ma) != len(mb):
        diffs.append({"field": "messages", "detail": f"条数 {len(ma)} → {len(mb)}"})
    for i, (x, y) in enumerate(zip(ma, mb)):
        if x.get("role") != y.get("role"):
            diffs.append({"field": f"messages[{i}].role", "detail": f"{x.get('role')} → {y.get('role')}"})
        cx, cy = (x.get("content") or "").encode("utf-8"), (y.get("content") or "").encode("utf-8")
        if cx != cy:
            diffs.append({"field": f"messages[{i}].content({x.get('role')})",
                          "detail": "\n".join(_text_diff(x.get("content") or "", y.get("content") or ""))})
    return diffs


def compare_requests(source: list[dict[str, Any]], replay: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """逐任务比对请求。返回差异列表(空 = 全部逐字节一致)"""
    src, rep = {r["key"]: r for r in source}, {r["key"]: r for r in replay}
    diffs = []
    for key in keys:
        a = _request(src[key]) if key in src else None
        b = _request(rep[key]) if key in rep else None
        if b is None:
            diffs.append({"key": key, "field": "记录", "detail": "回放运行里没有这条记录,或上游调用不是恰好 1 次"})
            continue
        diffs += [{"key": key, **d} for d in request_diffs(a, b)]
    return diffs


def check_alignment(source: list[dict[str, Any]], replay: list[dict[str, Any]], keys: list[str]) -> list[str]:
    """回放运行每条记录拿到的模型输出,必须与源运行同 key 的逐字节相同(证明场景没有错位、响应没被改写)"""
    src, rep = {r["key"]: r for r in source}, {r["key"]: r for r in replay}
    bad = []
    for key in keys:
        ra, rb = (src.get(key) or {}).get("upstream") or [], (rep.get(key) or {}).get("upstream") or []
        if len(rb) != 1 or rb[0].get("status") != 200:
            bad.append(f"{key}: 回放上游 {[u.get('status') for u in rb]}")
            continue
        for f in ("content", "response_model", "system_fingerprint"):
            if ra[0].get(f) != rb[0].get(f):
                bad.append(f"{key}: {f} 与源运行不同")
    return bad


def summarize(diffs: list[dict[str, Any]]) -> dict[str, Any]:
    by_field: dict[str, int] = {}
    for d in diffs:
        by_field[d["field"]] = by_field.get(d["field"], 0) + 1
    keys = sorted({d["key"] for d in diffs})
    scenes: dict[str, int] = {}
    for k in keys:
        scenes[k.split("|")[1]] = scenes.get(k.split("|")[1], 0) + 1
    return {"requests_differ": len(keys), "by_field": dict(sorted(by_field.items())), "by_scene": dict(sorted(scenes.items())),
            "keys": keys}


def render_check(source_rel: str, replay_rel: str, total: int, diffs: list[dict[str, Any]], misaligned: list[str]) -> str:
    sm = summarize(diffs)
    ok = not diffs and not misaligned
    L = [f"<!-- replay-check source={source_rel} replay={replay_rel} -->",
         "# 回放验证:v2 发给模型的请求是否与源运行逐字节一致", "",
         f"- 源运行:`{source_rel}`", f"- 回放运行:`{replay_rel}`",
         f"- 比对的任务数:{total}(每个任务恰好一次上游调用)",
         "- 比对内容:model、temperature、max_tokens、response_format,以及全部 messages 的 role 与 content(UTF-8 字节)",
         f"- **结论:{'一致——可以复用源运行的模型输出' if ok else '不一致——停止,不出 v2 结果报告'}**", "",
         f"复现(不发请求,只读两个运行目录):`python tests/llm_security/run_eval.py replay-check {source_rel} {replay_rel}`", "",
         "## 1. 汇总", "",
         f"- 请求不一致的任务:{sm['requests_differ']} / {total}",
         f"- 按场景:{json.dumps(sm['by_scene'], ensure_ascii=False) if sm['by_scene'] else '无'}",
         f"- 按字段:{json.dumps(sm['by_field'], ensure_ascii=False) if sm['by_field'] else '无'}",
         f"- 回放对齐(每条拿到的模型输出与源运行同 key 逐字节相同):{'通过' if not misaligned else f'{len(misaligned)} 条不通过'}", ""]
    if misaligned:
        L += ["## 2. 对齐失败", ""] + [f"- {x}" for x in misaligned[:50]] + [""]
    if diffs:
        L += ["## 3. 逐条差异(`-` 源运行,`+` 回放运行)", ""]
        for d in diffs:
            L += [f"### `{d['key']}` · {d['field']}", "", "```diff", d["detail"], "```", ""]
    return "\n".join(L).rstrip("\n") + "\n"
