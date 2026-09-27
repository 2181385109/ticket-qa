"""
混合回放(llmsec/hybrid.py、run_eval.py hybrid / hybrid-check / resample-compare)的离线用例:不起服务、不发请求。

1. 代理在请求到达时判定:与源运行一致 → 回放源输出、不转发;不一致且在预期集合里 → 转发(重新采样);不一致且不在集合里 → 拒绝。
2. 预算只计真正转发的调用;执行器遇到被拒绝的任务停止整次运行。
3. 预期集合 = 纯回放运行里请求不一致的任务;check 在集合不符、回放任务请求不一致时不通过。
4. 已提交的 hybrid_check.md / resample_compare.md 必须能由第一行注释里的运行目录逐字节重新生成。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import run_eval
from llmsec import hybrid as HY
from llmsec import proxy as PX
from llmsec import runner as RN

HERE = Path(__file__).resolve().parent


def _up(user: str, content: str) -> dict:
    return {"status": 200, "request": {"model": "m", "temperature": 0.3, "max_tokens": 300,
                                       "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": user}]},
            "response_model": "resp-m", "system_fingerprint": "fp", "usage": None, "content": content, "finish_reason": "stop",
            "t_utc": "t", "latency_ms": 1}


def _body(up: dict, user: str | None = None) -> bytes:
    req = copy.deepcopy(up["request"])
    if user is not None:
        req["messages"][1]["content"] = user
    return json.dumps(req, ensure_ascii=False).encode("utf-8")


class _Proxy(HY.HybridProxy):
    """不起 HTTP 服务;把"转发到上游"换成一个计数的假上游"""

    def __init__(self, source, resample):
        super().__init__("http://upstream.invalid", source, resample)
        self.upstream_calls = 0

    def _forward(self, *a):
        self.upstream_calls += 1
        resp = {"model": "resp-m", "system_fingerprint": "fp2", "choices": [{"message": {"content": "新采样"}, "finish_reason": "stop"}]}
        return 200, json.dumps(resp, ensure_ascii=False).encode("utf-8"), "application/json", None, {}


@pytest.fixture
def proxy(monkeypatch):
    source = {"C-001|draft|0": _up("分类:REFUND\n标题:x", "旧草稿"), "N-001|draft|0": _up("分类:OTHER\n标题:y", "对照草稿")}
    p = _Proxy(source, {"C-001|draft|0"})
    monkeypatch.setattr(PX.RecordingProxy, "respond", lambda self, *a: self._forward(*a))
    return p


def test_identical_request_replays_source_output_without_forwarding(proxy):
    proxy.current_key = "C-001|draft|0"
    status, body, _, _, extra = proxy.respond("POST", "/chat/completions", _body(proxy.source["C-001|draft|0"]), {})
    assert (status, extra["hybrid"], proxy.upstream_calls, proxy.forwarded) == (200, "replay", 0, 0)
    assert json.loads(body)["choices"][0]["message"]["content"] == "旧草稿"


def test_changed_request_in_expected_set_is_resampled(proxy):
    proxy.current_key = "C-001|draft|0"
    status, body, _, _, extra = proxy.respond("POST", "/chat/completions", _body(proxy.source["C-001|draft|0"], "分类:BILLING\n标题:x"), {})
    assert (status, extra["hybrid"], proxy.upstream_calls, proxy.forwarded) == (200, "resample", 1, 1)
    assert json.loads(body)["choices"][0]["message"]["content"] == "新采样"


def test_changed_request_outside_expected_set_is_refused(proxy):
    proxy.current_key = "N-001|draft|0"
    status, _, _, _, extra = proxy.respond("POST", "/chat/completions", _body(proxy.source["N-001|draft|0"], "分类:TECH\n标题:y"), {})
    assert (status, extra["hybrid"], proxy.upstream_calls) == (502, "blocked", 0)
    assert "不在预期的重采样集合里" in extra["hybrid_reason"]
    proxy.current_key = "X-999|draft|0"
    assert proxy.respond("POST", "/", b"{}", {})[4]["hybrid"] == "blocked", "源运行没有的任务一律拒绝"


def test_budget_counts_only_forwarded_and_executor_stops_on_refusal(proxy, tmp_path):
    budget = RN.Budget(tmp_path / "b.json", limit=10)
    hb = HY.HybridBudget(budget, proxy)
    proxy.current_key = "C-001|draft|0"
    proxy.respond("POST", "/", _body(proxy.source["C-001|draft|0"]), {})
    hb.add("run", 1)
    assert budget.total == 0, "回放不计入预算"
    proxy.respond("POST", "/", _body(proxy.source["C-001|draft|0"], "分类:BILLING\n标题:x"), {})
    hb.add("run", 1)
    assert budget.total == 1

    def inner(task, sample, ticket_id):
        return {"key": task.key, "upstream": [{"hybrid": "blocked", "hybrid_reason": "测试"}]}
    ex = HY.HybridExecutor(inner, proxy)
    with pytest.raises(RN.StopRun, match="混合回放前提不成立"):
        ex(RN.Task("N-001", "draft", 0), {}, 1)
    assert proxy.current_key is None


def _rec(key: str, up: dict, origin: str | None = None) -> dict:
    u = copy.deepcopy(up)
    if origin:
        u["hybrid"] = origin
    return {"key": key, "sample_id": key.split("|")[0], "scene": key.split("|")[1], "upstream": [u]}


def test_expected_set_and_check():
    a, b = _up("分类:REFUND\n标题:x", "旧"), _up("分类:OTHER\n标题:y", "对照")
    v1 = [_rec("C-001|draft|0", a), _rec("N-001|draft|0", b)]
    changed = copy.deepcopy(a)
    changed["request"]["messages"][1]["content"] = "分类:BILLING\n标题:x"
    replay = [_rec("C-001|draft|0", changed), _rec("N-001|draft|0", b)]
    keys = ["C-001|draft|0", "N-001|draft|0"]
    expected = HY.expected_resample(v1, replay, keys)
    assert expected == ["C-001|draft|0"]

    resampled = copy.deepcopy(changed)
    resampled["content"] = "新"
    hy = [_rec("C-001|draft|0", resampled, "resample"), _rec("N-001|draft|0", b, "replay")]
    res = HY.check(v1, hy, keys, expected)
    assert res["ok"] and res["replayed"] == ["N-001|draft|0"] and res["resampled"] == expected

    bad = [_rec("C-001|draft|0", resampled, "resample"), _rec("N-001|draft|0", {**b, "content": "被改写"}, "replay")]
    assert any("content 与 v1 不同" in p for p in HY.check(v1, bad, keys, expected)["problems"])
    assert any("与预期集合不同" in p for p in HY.check(v1, hy, keys, [])["problems"])


def test_committed_hybrid_reports_regenerate_byte_identical():
    for path in sorted((HERE / "reports").glob("*/hybrid_check.md")):
        src, hyb, rep = HY.sources(path, "hybrid-check")
        committed = path.read_bytes()
        try:
            run_eval.hybrid_check(RN.REPO / src, RN.REPO / hyb, RN.REPO / rep)
            assert path.read_bytes() == committed, f"{path} 不能由三个运行目录逐字节重新生成"
        finally:
            path.write_bytes(committed)
    for path in sorted((HERE / "reports").glob("*/resample_compare.md")):
        src, hyb = HY.sources(path, "resample-compare")
        committed = path.read_bytes()
        try:
            run_eval.resample_compare(RN.REPO / src, RN.REPO / hyb)
            assert path.read_bytes() == committed, f"{path} 不能由两个运行目录逐字节重新生成"
        finally:
            path.write_bytes(committed)
