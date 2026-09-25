"""
报告生成的离线用例(进 CI)。

1. 用构造的假运行(fixtures/fake_run.py)逐项断言报告里的数字——报告的数字就是交付物,算错一个就是编造。
2. "已提交的 raw 重新生成报告,必须与已提交的 report.md 逐字节一致"——对 fixtures/fake-run 和 reports/ 下每个运行目录都成立。
   这条保证报告里的每个数字都能由 `run_eval.py rejudge` 从原始记录复现;改了标签没 rejudge 也会红。
3. 改标签后离线重判:不发任何网络请求,结果随标签变化;改了样本文本则拒绝判定。
"""
from __future__ import annotations

import copy
import json
import shutil
import socket
from pathlib import Path

import pytest

import run_eval
from fixtures import fake_run
from llmsec import dataset as dsmod
from llmsec import judge as J
from llmsec import report as R
from llmsec import runner as RN

HERE = Path(__file__).resolve().parent


@pytest.fixture()
def fake(tmp_path):
    d = fake_run.build(tmp_path / "fake-run")
    ds = dsmod.load(d / "data")
    lists = J.load_lists(d / "data")
    meta, records, dups = R.load_run(d)
    return d, ds, lists, R.compute(meta, records, ds, lists, dups)


@pytest.fixture()
def no_network(monkeypatch):
    """离线重判不许发请求:任何 socket 连接直接失败"""
    def refuse(*a, **kw):
        raise AssertionError("离线重判发起了网络连接")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# ---------------------------------------------------------------------- 数字逐项

def test_attack_a_numbers(fake):
    *_, st = fake
    a = st["attacks"]["A"]["e2e"]["all"]
    assert (a["runs_success"], a["runs_valid"]) == (1, 2)
    assert (a["samples_success"], a["samples_with_valid"]) == (1, 1)
    assert a["flips"] == 1
    assert a["dist"] == {0: 0, 1: 1, 2: 0}
    assert (a["runs_secondary"], a["samples_secondary"]) == (1, 1)            # 严格口径 =P0
    assert (a["twin_runs_success"], a["twin_runs_valid"]) == (1, 2)           # 基底 N-001 众数 P2


def test_attack_b_numbers_and_invalid_run(fake):
    *_, st = fake
    b = st["attacks"]["B"]["e2e"]["all"]
    assert (b["runs_success"], b["runs_valid"]) == (1, 1)                     # BAD_RESPONSE 那次不进分母
    assert b["samples_partial"] == 1 and b["dist"] == {0: 0, 1: 0, 2: 0}
    assert (b["twin_runs_success"], b["twin_runs_valid"]) == (1, 1)
    assert st["calls"]["bad_response_attacks"] == ["B-001|classify|1"]
    m = st["attacks"]["B"]["model"]["all"]
    assert (m["runs_success"], m["runs_valid"]) == (1, 1)                     # 模型层:格式破坏不进分母


def test_uncertain_versions(fake):
    *_, st = fake
    assert st["attacks"]["B"]["e2e"]["certain"]["samples_total"] == 0         # 基底 N-002 标 ⚠,A/B 继承
    assert st["attacks"]["C"]["e2e"]["certain"]["samples_total"] == 1         # C/D 不继承
    assert st["controls"]["e2e"]["certain"]["samples"] == 1


def test_attack_c_d_numbers(fake):
    *_, st = fake
    c = st["attacks"]["C"]["e2e"]["all"]
    assert (c["runs_success"], c["runs_valid"]) == (2, 2)                     # 含否定句误判(已知局限)
    assert c["group_runs"] == {"deadline": 1, "refund": 2}
    d = st["attacks"]["D"]["e2e"]["all"]
    assert (d["runs_success"], d["runs_valid"], d["flips"]) == (1, 2, 1)


def test_control_numbers(fake):
    *_, st = fake
    c = st["controls"]["e2e"]["all"]
    assert (c["runs_valid"], c["cat_ok"], c["pri_ok"], c["both_ok"]) == (3, 3, 3, 3)
    assert (c["samples_all_ok"], c["samples_with_valid"]) == (2, 2)
    assert (c["draft_promise_runs"], c["draft_runs_valid"]) == (1, 4)
    assert (c["draft_samples_promise"], c["draft_samples_with_valid"]) == (1, 2)
    assert c["review_seen"] is False


def test_call_numbers(fake):
    *_, st = fake
    calls = st["calls"]
    assert calls["records"] == 18 and calls["upstream_calls"] == 18
    assert calls["invalid"]["e2e"] == {"classify:BAD_RESPONSE": 2}
    assert calls["invalid"]["model"] == {"classify:FORMAT_BROKEN": 2}
    assert calls["tokens"]["total_tokens"] == 18 * 110
    assert calls["latency"]["draft"]["ge_timeout"] == 1
    assert calls["response_models"] == {"fake-model": 18}


def test_rendered_report_carries_fractions_and_warning(fake):
    d, ds, lists, st = fake
    md = R.render(st, ds, d.name)
    assert "标签未经人工确认" in md
    assert "攻击集与防御同源" in md
    assert "1/2 (50.0%)" in md
    assert "«全额退款»" in md


def test_hits_list_negation_case(fake):
    *_, st = fake
    ctx = [h["context"] for h in st["hits"] if h["key"] == "C-001|draft|1"]
    assert any("无法承诺«全额退款»" in c for c in ctx)


# ---------------------------------------------------------------------- 可复现

def _run_dirs_with_report() -> list[Path]:
    dirs = [fake_run.FAKE_DIR]
    reports = HERE / "reports"
    if reports.exists():
        dirs += sorted(p for p in reports.iterdir()
                       if p.is_dir() and (p / "raw.jsonl").exists() and (p / "report.md").exists())
    return dirs


@pytest.mark.parametrize("run_dir", _run_dirs_with_report(), ids=lambda p: p.name)
def test_committed_report_regenerates_identically(run_dir, no_network):
    data_dir = run_dir / "data" if (run_dir / "data").exists() else dsmod.DATA_DIR
    ds = dsmod.load(data_dir)
    if RN.read_meta(run_dir).get("phase") == "holdout":
        ds = dsmod.Dataset(controls=ds.controls, attacks=ds.attacks + dsmod.load_holdout(data_dir))
    regenerated = R.generate(run_dir, ds, J.load_lists(data_dir))
    committed = (run_dir / "report.md").read_text(encoding="utf-8")
    assert regenerated == committed, (f"{run_dir.name}/report.md 与从 raw.jsonl 重新生成的不一致:"
                                      f"执行 python tests/llm_security/run_eval.py rejudge {run_dir}")


def test_fake_fixture_is_what_builder_produces(tmp_path):
    """防止有人手改 fixtures/fake-run 里的 raw 而不改构造器"""
    d = fake_run.build(tmp_path / "x")
    for name in ("raw.jsonl", "meta.json", "data/controls.jsonl", "data/attacks.jsonl"):
        assert (d / name).read_text(encoding="utf-8") == (fake_run.FAKE_DIR / name).read_text(encoding="utf-8"), name


# ---------------------------------------------------------------------- 离线重判

def test_rejudge_after_label_change_uses_new_labels_without_network(tmp_path, no_network):
    d = fake_run.build(tmp_path / "fake-run")
    data = d / "data"
    run_eval.rejudge_one(d, data_dir=data)
    before = (d / "report.md").read_text(encoding="utf-8")

    # 作者审核:全部确认,并把 N-001 的期望优先级从 P2 改成 P1(会同步到以它为基底的 A-001)
    ds = dsmod.load(data)
    csv_path = tmp_path / "review.csv"
    dsmod.export_review(ds, csv_path)
    import csv
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = list(csv.DictReader(f))
    for r in reader:
        r["确认(Y)"] = "Y"
        if r["id"] == "N-001":
            r["改为优先级"] = "P1"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=dsmod.REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(reader)
    dsmod.apply_review(ds, csv_path, reviewer="测试", today="2026-01-02")
    dsmod.save(ds, data)

    run_eval.rejudge_one(d, data_dir=data)
    after = (d / "report.md").read_text(encoding="utf-8")
    assert after != before
    assert "标签未经人工确认" not in after
    meta, records, _ = R.load_run(d)
    st = R.compute(meta, records, dsmod.load(data), J.load_lists(data))
    a = st["attacks"]["A"]["e2e"]["all"]
    assert (a["runs_success"], a["runs_valid"]) == (1, 2)           # P0 比 P1 仍更紧急;P2 不再算
    assert st["controls"]["e2e"]["all"]["pri_ok"] == 1              # N-001 两次 P2 都不再对


def test_rejudge_refuses_changed_sample_text(tmp_path):
    d = fake_run.build(tmp_path / "fake-run")
    data = d / "data"
    ds = dsmod.load(data)
    ds.controls[0]["content"] += "(改过)"
    dsmod.save(ds, data)
    with pytest.raises(ValueError, match="文本指纹"):
        run_eval.rejudge_one(d, data_dir=data)


def test_duplicate_raw_keys_are_counted_not_double_counted(tmp_path):
    d = fake_run.build(tmp_path / "fake-run")
    raw = d / "raw.jsonl"
    first = raw.read_text(encoding="utf-8").splitlines()[0]
    with open(raw, "a", encoding="utf-8", newline="\n") as f:
        f.write(first + "\n")
    meta, records, dups = R.load_run(d)
    assert dups == 1 and len(records) == 18


# ---------------------------------------------------------------------- plan 的数字

def test_plan_numbers_match_the_plan_doc():
    """计划 §4 的调用次数表由这条命令复现:run_eval.py plan"""
    s = RN.plan_summary(dsmod.load().samples, 5)
    assert s == {"A/B 分类": 110, "对照分类": 160, "C/D 建单": 18, "C/D 草稿": 90, "对照草稿": 160, "合计": 538}
    assert len(RN.PILOT_TASKS) == 5
