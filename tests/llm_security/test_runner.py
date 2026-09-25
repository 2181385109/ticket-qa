"""
执行器的离线用例(进 CI):断点续跑不重复、停止条件、预算、录制代理不落 Authorization。
执行器用假的 executor 注入(不连服务、不连上游);代理用本机起的假上游(只连 127.0.0.1)。
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from llmsec import runner as RN
from llmsec.proxy import RecordingProxy, summarize

SAMPLES = [
    {"id": "A-001", "group": "attack", "attack_class": "A"},
    {"id": "C-001", "group": "attack", "attack_class": "C"},
    {"id": "N-001", "group": "control", "attack_class": None},
]


def ok_record(task, sample, ticket_id, status=200):
    return {"key": task.key, "sample_id": task.sample_id, "scene": task.scene, "repeat": task.repeat,
            "ticket_id": ticket_id or 1000 + task.repeat, "api": {"status": 200, "data": {"id": 1}},
            "upstream": [{"status": status, "content": "{}"}]}


class Recorder:
    """记录每个 key 被执行了几次;可以在第 n 次执行时模拟中断 / 按脚本返回上游状态"""

    def __init__(self, interrupt_at=None, statuses=None):
        self.calls = []
        self.interrupt_at = interrupt_at
        self.statuses = list(statuses or [])

    def __call__(self, task, sample, ticket_id):
        if self.interrupt_at is not None and len(self.calls) == self.interrupt_at:
            raise KeyboardInterrupt("模拟会话被掐断")
        self.calls.append(task.key)
        status = self.statuses.pop(0) if self.statuses else 200
        return ok_record(task, sample, ticket_id, status)


@pytest.fixture()
def budget(tmp_path):
    return RN.Budget(tmp_path / "budget.json", limit=1000)


def test_plan_is_round_interleaved_and_cd_create_once():
    tasks = RN.plan_tasks(SAMPLES, 3)
    keys = [t.key for t in tasks]
    assert keys[:5] == ["A-001|classify|0", "C-001|classify|0", "C-001|draft|0", "N-001|classify|0", "N-001|draft|0"]
    assert "C-001|classify|1" not in keys and "C-001|draft|2" in keys
    assert len(keys) == len(set(keys))


def test_resume_after_interrupt_executes_each_key_once(tmp_path, budget):
    tasks = RN.plan_tasks(SAMPLES, 3)
    first = Recorder(interrupt_at=4)
    with pytest.raises(KeyboardInterrupt):
        RN.Runner(tmp_path, SAMPLES, tasks, first, budget, log=lambda m: None).run()
    second = Recorder()
    result = RN.Runner(tmp_path, SAMPLES, tasks, second, budget, log=lambda m: None).run()
    assert sorted(first.calls + second.calls) == sorted(t.key for t in tasks)      # 每个 key 恰好一次
    raw = RN.read_raw(tmp_path / "raw.jsonl")
    assert sorted(r["key"] for r in raw) == sorted(t.key for t in tasks)
    assert result == {"total": len(tasks), "done": len(tasks), "executed": len(second.calls)}
    assert budget.total == len(tasks)


def test_draft_reuses_ticket_of_first_classify(tmp_path, budget):
    seen = {}

    def ex(task, sample, ticket_id):
        seen[task.key] = ticket_id
        rec = ok_record(task, sample, ticket_id)
        if task.scene == "classify":
            rec["ticket_id"] = 500 + task.repeat
        return rec

    RN.Runner(tmp_path, SAMPLES, RN.plan_tasks(SAMPLES, 2), ex, budget, log=lambda m: None).run()
    assert seen["C-001|draft|1"] == 500 and seen["N-001|draft|1"] == 500


def test_isolated_failure_is_kept_as_a_result(tmp_path, budget):
    tasks = RN.plan_tasks(SAMPLES, 1)
    rec = Recorder(statuses=[500, 200])
    RN.Runner(tmp_path, SAMPLES, tasks, rec, budget, log=lambda m: None).run()
    raw = {r["key"]: r for r in RN.read_raw(tmp_path / "raw.jsonl")}
    assert raw[tasks[0].key]["upstream"][0]["status"] == 500
    assert not (tmp_path / "failures.jsonl").exists()


def test_three_failures_wait_then_retry_then_continue(tmp_path, budget):
    tasks = RN.plan_tasks(SAMPLES, 1)
    slept = []
    rec = Recorder(statuses=[503, 503, 503])
    RN.Runner(tmp_path, SAMPLES, tasks, rec, budget, sleep=slept.append, log=lambda m: None).run()
    assert slept == [RN.RETRY_WAIT_SECONDS]
    assert len(RN.read_raw(tmp_path / "failures.jsonl")) == 3
    raw = RN.read_raw(tmp_path / "raw.jsonl")
    assert sorted(r["key"] for r in raw) == sorted(t.key for t in tasks)
    assert all(r["upstream"][0]["status"] == 200 for r in raw)                  # 失败的那 3 条重试后成功,不留在 raw


def test_failures_after_retry_stop_the_run(tmp_path, budget):
    tasks = RN.plan_tasks(SAMPLES, 1)
    rec = Recorder(statuses=[503] * 10)
    with pytest.raises(RN.StopRun, match="停止条件 2"):
        RN.Runner(tmp_path, SAMPLES, tasks, rec, budget, sleep=lambda s: None, log=lambda m: None).run()
    assert RN.read_raw(tmp_path / "raw.jsonl") == []
    assert len(RN.read_raw(tmp_path / "failures.jsonl")) == 6
    # 续跑时这些任务还会被重试(不在 raw 里)
    rec2 = Recorder()
    RN.Runner(tmp_path, SAMPLES, tasks, rec2, budget, log=lambda m: None).run()
    assert sorted(rec2.calls) == sorted(t.key for t in tasks)


def test_auth_failure_stops_immediately(tmp_path, budget):
    rec = Recorder(statuses=[401])
    with pytest.raises(RN.StopRun, match="停止条件 1"):
        RN.Runner(tmp_path, SAMPLES, RN.plan_tasks(SAMPLES, 1), rec, budget, log=lambda m: None).run()
    assert len(rec.calls) == 1


def test_budget_stops_before_exceeding_limit(tmp_path):
    b = RN.Budget(tmp_path / "budget.json", limit=3)
    rec = Recorder()
    with pytest.raises(RN.StopRun, match="停止条件 3"):
        RN.Runner(tmp_path, SAMPLES, RN.plan_tasks(SAMPLES, 2), rec, b, log=lambda m: None).run()
    assert len(rec.calls) == 3 and b.total == 3
    assert json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))["total"] == 3   # 跨会话持久化


def test_budget_file_in_repo_is_consistent():
    """仓库里的累计计数 = 各运行之和,且不超过上限"""
    b = RN.Budget()
    assert b.total == sum(b.state["runs"].values())
    assert b.total <= b.limit


# ---------------------------------------------------------------------- 录制代理

def test_summarize_extracts_fields_without_headers():
    req = json.dumps({"model": "m-req", "temperature": 0, "messages": [{"role": "user", "content": "你好"}]}).encode()
    resp = json.dumps({"model": "m-resp", "system_fingerprint": "fp1", "usage": {"total_tokens": 3},
                       "choices": [{"message": {"content": "{\"category\":\"OTHER\"}"}, "finish_reason": "stop"}]}).encode()
    r = summarize("POST", "/chat/completions", req, 200, resp, 12, None)
    assert (r["request_model"], r["response_model"], r["system_fingerprint"]) == ("m-req", "m-resp", "fp1")
    assert r["content"] == "{\"category\":\"OTHER\"}" and r["request"]["messages"][0]["content"] == "你好"
    assert "headers" not in r


def test_summarize_non_json_body():
    r = summarize("POST", "/chat/completions", b"", 502, b"<html>bad gateway</html>", 5, None)
    assert r["content"] is None and "bad gateway" in r["response_text"]


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_proxy_forwards_and_records_but_never_stores_authorization():
    received = {}

    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            received["auth"] = self.headers.get("Authorization")
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received["body"] = body
            out = json.dumps({"model": "up-model", "choices": [{"message": {"content": "ok"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    up = ThreadingHTTPServer(("127.0.0.1", _free_port()), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    proxy = RecordingProxy(f"http://127.0.0.1:{up.server_address[1]}", port=_free_port()).start()
    try:
        body = json.dumps({"model": "m", "messages": [{"role": "user", "content": "标题:测试"}]}, ensure_ascii=False).encode()
        r = requests.post(proxy.url + "/chat/completions", data=body,
                          headers={"Authorization": "Bearer sk-secret-value", "Content-Type": "application/json"}, timeout=10)
        assert r.status_code == 200 and r.json()["model"] == "up-model"
        assert received["auth"] == "Bearer sk-secret-value" and received["body"] == body     # 原样转发
        recs = proxy.drain()
        assert len(recs) == 1 and recs[0]["content"] == "ok" and recs[0]["response_model"] == "up-model"
        assert "sk-secret-value" not in json.dumps(recs, ensure_ascii=False)                  # 不落 key
        assert proxy.drain() == []
    finally:
        proxy.stop()
        up.shutdown()


def test_proxy_upstream_unreachable_returns_502_and_records_error():
    proxy = RecordingProxy(f"http://127.0.0.1:{_free_port()}", port=_free_port(), timeout=3).start()
    try:
        r = requests.post(proxy.url + "/chat/completions", data=b"{}", timeout=10)
        assert r.status_code == 502
        rec = proxy.drain()[0]
        assert rec["status"] is None and rec["error"]
    finally:
        proxy.stop()
