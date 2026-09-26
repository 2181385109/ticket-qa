"""
基线复跑(--attacks-only)与复跑对比报告(llmsec/rerun.py)的离线用例。

1. --attacks-only 的任务规划只有攻击样本;报告只数本次跑了的样本,对照组不以"0 次有效运行"混进分母。
2. 三次运行并排:数字来自各自的运行目录;conclusion.md 原样附在文末;确定性。
3. 已提交的 rerun_compare.md 必须能由第一行注释里的三个运行目录(加同目录 conclusion.md)逐字节重新生成。
"""
from __future__ import annotations

import json
from pathlib import Path

import run_eval
from fixtures import fake_run
from llmsec import dataset as dsmod
from llmsec import judge as J
from llmsec import report as R
from llmsec import rerun as RR
from llmsec import runner as RN

HERE = Path(__file__).resolve().parent


def _attacks_only_run(target: Path) -> Path:
    d = fake_run.build(target)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    ds = dsmod.load(d / "data")
    meta.update(attacks_only=True, sample_ids=sorted(s["id"] for s in ds.attacks))
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    rows = [r for r in RN.read_raw(d / "raw.jsonl") if not r["sample_id"].startswith("N-")]
    (d / "raw.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
    return d


def test_attacks_only_plan_has_no_controls():
    ds = dsmod.load()
    tasks = RN.plan_tasks(run_eval.attacks_only(ds.samples), 5)
    assert all(not t.sample_id.startswith("N-") for t in tasks)
    s = RN.plan_summary(run_eval.attacks_only(ds.samples), 5)
    assert (s["对照分类"], s["对照草稿"], s["合计"]) == (0, 0, 218)


def test_attacks_only_report_counts_only_run_samples(tmp_path):
    d = _attacks_only_run(tmp_path / "rr")
    ds = dsmod.load(d / "data")
    meta, records, dups = R.load_run(d)
    st = R.compute(meta, records, ds, J.load_lists(d / "data"), dups)
    assert st["controls"]["e2e"]["all"]["samples"] == 0, "对照组不在本次运行里,不计入"
    assert st["attacks"]["A"]["e2e"]["all"]["runs_valid"] == 2


def test_three_way_render_is_deterministic_and_appends_conclusion(tmp_path):
    p1 = fake_run.build(tmp_path / "p1")
    rr = _attacks_only_run(tmp_path / "rr")
    af = fake_run.build(tmp_path / "af")
    ds, lists = dsmod.load(p1 / "data"), J.load_lists(p1 / "data")
    a = RR.generate(p1, rr, af, ds, lists)
    assert a == RR.generate(p1, rr, af, ds, lists)
    assert "## 6. 结论" not in a
    (rr / RR.CONCLUSION_FILE).write_text("复跑与基线相同。\n", encoding="utf-8")
    b = RR.generate(p1, rr, af, ds, lists)
    assert b.rstrip().endswith("复跑与基线相同。")
    row = next(line for line in b.splitlines() if "| A 优先级提权 | 原口径·宽松" in line)
    assert row.count("1/2 (50.0%)") == 3, "三列都来自同一份假数据:A-001 两轮里一轮 P0"
    assert "只跑攻击样本" in b


def test_committed_rerun_compares_regenerate_byte_identical():
    for path in sorted((HERE / "reports").glob(f"*/{RR.OUT_FILE}")):
        src = RR.sources(path)
        assert src, path
        text = RR.generate(*src, dsmod.load(), J.load_lists(dsmod.DATA_DIR))
        assert text.encode("utf-8") == path.read_bytes(), f"{path} 不能由三个运行目录逐字节重新生成"
