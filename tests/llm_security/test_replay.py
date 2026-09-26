"""
回放评估(llmsec/replay.py、run_eval.py replay / replay-check)的离线用例:不起服务、不连 WireMock、不发请求。

1. 桩:一个全局场景按任务顺序串成链,第 i 个桩只在 step-i 匹配;响应体 base64 编码、解码后字段与源运行原样一致。
2. 用一个按 WireMock 场景语义写的模拟上游,驱动真正的 Runner 走完回放:每个任务拿到源运行同 key 的输出(对齐),预算文件不动。
3. 请求逐字节比对:一致 → 无差异;草稿 user 消息里的分类变了 → 报出 key 与差异行;少记录 → 报出。
4. 源运行不满足前提(某任务不是恰好一次上游调用)→ 拒绝回放。
5. 已提交的 replay_check.md 必须能由第一行注释里的两个运行目录逐字节重新生成。
"""
from __future__ import annotations

import base64
import copy
import json
import re
from pathlib import Path

import pytest

import run_eval
from fixtures import fake_run
from llmsec import dataset as dsmod
from llmsec import replay as RP
from llmsec import runner as RN

HERE = Path(__file__).resolve().parent


def _source():
    """假源运行:fake_run 的记录,补上代理会录到的请求体"""
    recs = fake_run.records()
    for r in recs:
        role_user = f"<ticket>{r['sample_id']}</ticket>" if r["scene"] == "classify" else f"分类:REFUND\n标题:{r['sample_id']}"
        r["upstream"][0].update(request={"model": "fake-request-model", "temperature": 0, "max_tokens": 200,
                                         "response_format": {"type": "json_object"},
                                         "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": role_user}]},
                                finish_reason="stop")
    return recs


def _tasks():
    ctrl, atk = fake_run.samples()
    return RN.plan_tasks(ctrl + atk, 2)


def test_stubs_form_one_chain_in_task_order():
    calls = RP.source_calls(_source(), _tasks())
    stubs = RP.build_stubs(calls)
    assert [s["metadata"]["llmReplay"]["key"] for s in stubs] == [t.key for t in _tasks()]
    assert stubs[0]["requiredScenarioState"] == "Started"
    for i, s in enumerate(stubs):
        assert s["scenarioName"] == RP.SCENARIO and s["newScenarioState"] == f"step-{i + 1}"
        if i:
            assert s["requiredScenarioState"] == stubs[i - 1]["newScenarioState"]
        assert "bodyPatterns" not in s["request"], "不按请求体匹配:不一致时照样回放,跑完再逐条判定"
    assert RP.build_stubs(calls) == stubs, "桩 id 确定(uuid5),重复加载是覆盖不是追加"


def test_body_is_base64_and_carries_recorded_fields():
    calls = RP.source_calls(_source(), _tasks())
    key, up = calls[3]
    body = json.loads(base64.b64decode(RP.build_stubs(calls)[3]["response"]["base64Body"]).decode("utf-8"))
    assert body["choices"][0]["message"]["content"] == up["content"]
    assert (body["model"], body["system_fingerprint"], body["usage"]) == (up["response_model"], up["system_fingerprint"], up["usage"])
    assert "body" not in RP.build_stubs(calls)[3]["response"], "文本 body 会经过 WireMock 全局响应模板;base64Body 不会"


class _ScenarioUpstream:
    """按 WireMock 场景语义模拟上游:当前状态 == requiredScenarioState 的桩匹配,返回它的响应并把状态推到 newScenarioState"""

    def __init__(self, stubs):
        self.stubs, self.state = stubs, "Started"

    def call(self, request):
        stub = next(s for s in self.stubs if s["requiredScenarioState"] == self.state)
        self.state = stub["newScenarioState"]
        body = json.loads(base64.b64decode(stub["response"]["base64Body"]))
        return {"status": 200, "request": request, "request_model": request["model"], "response_model": body["model"],
                "system_fingerprint": body["system_fingerprint"], "usage": body["usage"],
                "content": body["choices"][0]["message"]["content"], "finish_reason": body["choices"][0]["finish_reason"]}


def _replay(tmp_path, source, mutate=None):
    """用真正的 Runner 驱动一次回放;服务发出的请求 = 源运行的请求(可被 mutate 改写,模拟服务改变了模型输入)"""
    tasks = _tasks()
    upstream = _ScenarioUpstream(RP.build_stubs(RP.source_calls(source, tasks)))
    src = {r["key"]: r for r in source}

    def executor(task, sample, ticket_id):
        req = copy.deepcopy(src[task.key]["upstream"][0]["request"])
        if mutate:
            mutate(task, req)
        up = upstream.call(req)
        return {**{k: v for k, v in src[task.key].items() if k != "upstream"}, "upstream": [up]}

    ctrl, atk = fake_run.samples()
    run_dir = tmp_path / "replay"
    run_dir.mkdir()
    budget_file = tmp_path / "call_budget.json"
    budget_file.write_text('{"limit": 1, "total": 1, "runs": {}}', encoding="utf-8")
    RN.Runner(run_dir, ctrl + atk, tasks, executor, RP.NoBudget(), log=lambda _: None).run()
    assert budget_file.read_text(encoding="utf-8") == '{"limit": 1, "total": 1, "runs": {}}'
    return RN.read_raw(run_dir / "raw.jsonl"), [t.key for t in tasks], upstream


def test_runner_replays_each_task_its_own_output_without_touching_budget(tmp_path):
    source = _source()
    replayed, keys, upstream = _replay(tmp_path, source)
    assert upstream.state == f"step-{len(keys)}", "每个任务恰好消费一个桩"
    assert RP.check_alignment(source, replayed, keys) == []
    assert RP.compare_requests(source, replayed, keys) == []


def test_changed_draft_category_is_reported_byte_level(tmp_path):
    def mutate(task, req):
        if task.key == "C-001|draft|1":
            req["messages"][1]["content"] = req["messages"][1]["content"].replace("分类:REFUND", "分类:BILLING")
    source = _source()
    replayed, keys, _ = _replay(tmp_path, source, mutate)
    diffs = RP.compare_requests(source, replayed, keys)
    assert [(d["key"], d["field"]) for d in diffs] == [("C-001|draft|1", "messages[1].content(user)")]
    assert "-分类:REFUND" in diffs[0]["detail"] and "+分类:BILLING" in diffs[0]["detail"]
    assert RP.check_alignment(source, replayed, keys) == [], "请求变了,回放仍按任务顺序对齐——不一致由比对判出,不是由错位判出"
    text = RP.render_check("src", "rep", len(keys), diffs, [])
    assert "不一致——停止,不出 v2 结果报告" in text and "C-001|draft|1" in text


def test_other_request_fields_and_missing_records_are_reported(tmp_path):
    def mutate(task, req):
        if task.key == "A-001|classify|0":
            req["temperature"] = 0.3
    source = _source()
    replayed, keys, _ = _replay(tmp_path, source, mutate)
    diffs = RP.compare_requests(source, replayed[1:], keys)
    fields = {(d["key"], d["field"]) for d in diffs}
    assert (keys[0], "记录") in fields and len(diffs) == 1, "A-001|classify|0 是第一个任务,去掉后只报缺失"
    diffs = RP.compare_requests(source, replayed, keys)
    assert [(d["key"], d["field"], d["detail"]) for d in diffs] == [("A-001|classify|0", "temperature", "0 → 0.3")]


def test_source_without_exactly_one_upstream_call_is_refused():
    source = _source()
    source[0]["upstream"].append(copy.deepcopy(source[0]["upstream"][0]))
    with pytest.raises(RP.ReplayError, match="恰好 1 次"):
        RP.source_calls(source, _tasks())
    source = _source()
    source[1]["upstream"][0]["status"] = 500
    with pytest.raises(RP.ReplayError, match="上游状态 500"):
        RP.source_calls(source, _tasks())


def test_committed_replay_checks_regenerate_byte_identical(tmp_path):
    checks = sorted((HERE / "reports").glob("*/replay_check.md"))
    for path in checks:
        m = re.match(r"^<!-- replay-check source=(\S+) replay=(\S+) -->$", path.read_text(encoding="utf-8").split("\n", 1)[0])
        assert m, path
        committed = path.read_bytes()
        try:
            run_eval.replay_check(RN.REPO / m.group(1), RN.REPO / m.group(2))
            assert path.read_bytes() == committed, f"{path} 不能由两个运行目录逐字节重新生成"
        finally:
            path.write_bytes(committed)
