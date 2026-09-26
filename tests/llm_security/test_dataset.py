"""
测试集本身的离线校验(进 CI):格式、base_id 引用、类别配额、标签字段、裁判词表与 Java 提示词的一致性、审核表往返。
方法:数据集是被测对象——它错了,后面所有的攻击成功率都是错的,所以它和代码一样要有用例钉住(test-design/09 §7)。
"""
from __future__ import annotations

import copy
import csv
import json
import re
from pathlib import Path

import pytest

from llmsec import dataset as dsmod
from llmsec.textnorm import normalize

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
JAVA_CLIENT = REPO / "service/src/main/java/com/ticketqa/llm/LlmPrompts.java"          # 两个 system prompt(第二阶段从客户端里移出)
JAVA_POLICY = REPO / "service/src/main/java/com/ticketqa/llm/DraftOutputPolicy.java"   # 第二阶段草稿检查的防御词表


@pytest.fixture(scope="module")
def ds():
    return dsmod.load()


def java_prompt(name: str) -> str:
    src = JAVA_CLIENT.read_text(encoding="utf-8")
    m = re.search(name + r'\s*=\s*"""(.*?)""";', src, re.S)
    assert m, f"在 {JAVA_CLIENT.name} 里找不到 {name}"
    return m.group(1)


# ---------------------------------------------------------------------- 格式与引用

def test_dataset_is_valid(ds):
    assert dsmod.validate(ds) == []


def test_every_line_is_json_object():
    for name in (*dsmod.SAMPLE_FILES, "holdout.jsonl"):
        for i, line in enumerate((dsmod.DATA_DIR / name).read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                assert isinstance(json.loads(line), dict), f"{name}:{i}"


def test_holdout_is_valid_together_with_dataset(ds):
    """计划 D3(2026-09-26 修订):留出集由作者在防御定稿后亲手编写,可以为空;写了就必须和主数据集一起通过校验
    (id 不重复、基底存在、期望与基底一致、目标合法)——否则 holdout_compare.ps1 跑到一半才报错,白花真实调用"""
    assert (dsmod.DATA_DIR / "holdout.jsonl").exists()
    holdout = dsmod.load_holdout()
    assert dsmod.validate(dsmod.Dataset(controls=ds.controls, attacks=ds.attacks + holdout)) == []
    assert all(s["group"] == "attack" for s in holdout), "留出集只放攻击样本;基底用 controls.jsonl 里已有的"


def test_base_ids_point_to_controls(ds):
    controls = {c["id"] for c in ds.controls}
    assert {a["base_id"] for a in ds.attacks} <= controls


# ---------------------------------------------------------------------- 配额

def test_attack_quota(ds):
    q = dsmod.quota_report(ds)
    assert q["attacks"] == dsmod.ATTACK_QUOTA
    assert 30 <= len(ds.attacks) <= 50


def test_control_quota(ds):
    q = dsmod.quota_report(ds)
    assert q["controls"] == {c: dsmod.CONTROL_PER_CATEGORY for c in dsmod.CATEGORIES}
    assert len(ds.controls) >= 30
    # 三档优先级都要有,否则对照组测不出优先级判定的误伤
    assert {c["expected"]["priority"] for c in ds.controls} == set(dsmod.PRIORITIES)


def test_title_injections_per_class(ds):
    q = dsmod.quota_report(ds)
    for cls, n in q["title_injections"].items():
        assert n >= dsmod.MIN_TITLE_INJECTIONS_PER_CLASS, f"{cls} 类只有 {n} 条标题注入"


def test_every_technique_is_used(ds):
    q = dsmod.quota_report(ds)
    assert all(n > 0 for n in q["techniques"].values()), q["techniques"]


def test_keyword_stuffing_really_contains_rule_keywords(ds):
    """关键词填充样本必须真的夹带了规则分类器的词,否则它检验不了第二阶段交叉校验的这个弱点"""
    p0_words = ("紧急", "urgent", "无法登录", "崩溃", "全部用户", "生产", "宕机", "crash", "down")   # KeywordRuleClassifier.P0_KEYWORDS
    tech_words = ("报错", "崩溃", "无法登录", "打不开", "闪退", "登录", "bug", "crash", "error", "login", "404", "500")
    for a in ds.attacks:
        if a["technique"] != "keyword_stuffing":
            continue
        text = (a["title"] + " " + a["content"]).lower()
        words = p0_words if a["attack_class"] == "A" else tech_words
        assert any(w in text for w in words), a["id"]


# ---------------------------------------------------------------------- 标签

def test_label_fields_complete(ds):
    for s in ds.samples:
        assert s["label_status"] in dsmod.LABEL_STATUSES
        assert s["label_reason"].strip()
        assert isinstance(s["uncertain"], bool)


def test_uncertain_labels_say_why(ds):
    """标 ⚠ 的样本,理由里必须写出拿不准的是什么"""
    for s in ds.controls:
        if s["uncertain"]:
            assert "⚠" in s["label_reason"], s["id"]


def test_uncertain_scope_follows_adr(ds):
    """ADR-024 §5:A/B 继承基底的 ⚠,C/D 不继承"""
    for a in ds.attacks:
        base_unc = ds.by_id[a["base_id"]]["uncertain"]
        if a["attack_class"] in ("A", "B"):
            assert ds.is_uncertain(a["id"]) == (a["uncertain"] or base_unc)
        else:
            assert ds.is_uncertain(a["id"]) == a["uncertain"]


# ---------------------------------------------------------------------- 裁判词表

def test_leak_fragments_are_substrings_of_java_draft_prompt():
    """片段不在当前提示词里,D 类裁判就永远不会响——改提示词时这条会红"""
    prompt = normalize(java_prompt("DRAFT_SYSTEM_PROMPT"))
    frags = json.loads((dsmod.DATA_DIR / "judge_leak_fragments.json").read_text(encoding="utf-8"))["fragments"]
    assert frags
    for f in frags:
        assert normalize(f) in prompt, f


def java_defense_words() -> list[str]:
    src = JAVA_POLICY.read_text(encoding="utf-8")
    m = re.search(r"PROMISE_WORDS_BEGIN(.*?)PROMISE_WORDS_END", src, re.S)
    assert m, f"在 {JAVA_POLICY.name} 里找不到 PROMISE_WORDS_BEGIN / END 标记"
    body = re.sub(r"//[^\n]*", "", m.group(1))          # 去掉行注释(注释里的括号、引号不是词条)
    return re.findall(r'"([^"]+)"', body.split("List.of(", 1)[1])


def test_defense_words_are_subset_of_judge_words():
    """计划 §5:裁判词表是防御词表的超集。反过来就成了"防御拦什么、裁判就判什么",报告里"防御词表之外的命中"也无从统计"""
    groups = json.loads((dsmod.DATA_DIR / "judge_promise_keywords.json").read_text(encoding="utf-8"))["groups"]
    judge = {normalize(w) for ws in groups.values() for w in ws}
    defense = [normalize(w) for w in java_defense_words()]
    assert len(defense) >= 20
    assert [w for w in defense if w not in judge] == []
    assert len(defense) < len(judge), "裁判表必须严格大于防御表,否则'防御词表之外的命中'恒为 0,测不出换说法的绕过"


def test_promise_keywords_well_formed():
    groups = json.loads((dsmod.DATA_DIR / "judge_promise_keywords.json").read_text(encoding="utf-8"))["groups"]
    words = [normalize(w) for ws in groups.values() for w in ws]
    assert all(words)
    assert len(words) == len(set(words)), "词表有归一化后重复的词条"


# ---------------------------------------------------------------------- 指纹

def test_sha256_ignores_labels_but_not_text(ds):
    before = ds.text_sha256()
    d2 = copy.deepcopy(ds)
    d2.controls[0]["expected"]["priority"] = "P0"
    d2.controls[0]["uncertain"] = not d2.controls[0]["uncertain"]
    d2.controls[0]["label_status"] = "human_confirmed"
    assert d2.text_sha256() == before
    d2.controls[0]["content"] += "。"
    assert d2.text_sha256() != before


# ---------------------------------------------------------------------- 审核表往返

def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=dsmod.REVIEW_COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_review_roundtrip_propagates_control_label_to_attacks(ds, tmp_path):
    d = copy.deepcopy(ds)
    csv_path = tmp_path / "review.csv"
    assert dsmod.export_review(d, csv_path) == len(d.samples)
    rows = _rows(csv_path)
    assert list(rows[0].keys()) == dsmod.REVIEW_COLUMNS
    base_id = d.attacks[0]["base_id"]
    for r in rows:
        if r["id"] == base_id:
            r["改为分类"] = "BILLING" if d.by_id[base_id]["expected"]["category"] != "BILLING" else "TECH"
        else:
            r["确认(Y)"] = "Y"
    _write(csv_path, rows)
    stats = dsmod.apply_review(d, csv_path, reviewer="测试", today="2026-01-01")
    assert stats["changed"] == 1 and stats["confirmed"] == len(d.samples) - 1
    new_cat = d.by_id[base_id]["expected"]["category"]
    for a in d.attacks:
        if a["base_id"] == base_id:
            assert a["expected"]["category"] == new_cat
    assert d.all_human_confirmed()
    assert d.text_sha256() == ds.text_sha256()


def test_review_rejects_bad_enum_and_attack_label_edit(ds, tmp_path):
    csv_path = tmp_path / "review.csv"
    dsmod.export_review(copy.deepcopy(ds), csv_path)
    rows = _rows(csv_path)
    rows[0]["改为优先级"] = "P9"
    _write(csv_path, rows)
    with pytest.raises(ValueError, match="P9"):
        dsmod.apply_review(copy.deepcopy(ds), csv_path, reviewer="测试")
    rows = _rows(csv_path)
    attack_row = next(r for r in rows if r["组别"] == "攻击")
    attack_row["改为分类"] = "OTHER"
    _write(csv_path, rows)
    with pytest.raises(ValueError, match="继承自基底"):
        dsmod.apply_review(copy.deepcopy(ds), csv_path, reviewer="测试")


def test_validate_catches_broken_samples(ds):
    d = copy.deepcopy(ds)
    a = next(x for x in d.attacks if x["attack_class"] == "A")
    a["target"]["value"] = "P1"
    b = next(x for x in d.attacks if x["attack_class"] == "B")
    b["target"]["value"] = b["expected"]["category"]
    c = next(x for x in d.attacks if x["attack_class"] == "C")
    c["base_id"] = "N-999"
    errors = "\n".join(dsmod.validate(d))
    assert "A 类目标一律 P0" in errors
    assert "B 类目标等于期望类别" in errors
    assert "N-999" in errors
