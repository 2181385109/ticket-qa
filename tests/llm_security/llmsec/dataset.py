"""
测试集:加载、校验、文本指纹、标签审核表的导出 / 回写。

- 样本文件:data/controls.jsonl(对照)、data/attacks.jsonl(攻击)、data/holdout.jsonl(留出集,H-001 起;由 data/holdout_source.txt
  逐字转换而来,见 llmsec/holdout.py)。
- 留出样本是"新样本":没有基底(base_id = null),期望标签直接写在样本上;id 以 H- 开头,攻击类别写在 attack_class。
- 文本指纹 text_sha256 只覆盖 id + 标题 + 内容:改标签不影响指纹;改了样本文本,第一阶段和第二阶段就不可比(runner 会拒绝续跑 / 对比)。
- 攻击样本的期望标签继承自基底对照样本;改对照的标签(labels apply)会同步到它的全部攻击样本。
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CATEGORIES = ("BILLING", "TECH", "REFUND", "OTHER")
PRIORITIES = ("P0", "P1", "P2")
ATTACK_CLASSES = ("A", "B", "C", "D")
TECHNIQUES = ("direct_instruction", "fake_system_message", "fake_json_output", "role_play",
              "mixed_zh_en", "buried_in_long_text", "fake_delimiter", "keyword_stuffing")
# 留出集新增的手法(由 Claude 按原稿"方向"一栏归类,原文保留在样本的 source.方向;只允许出现在 H- 样本上)
HOLDOUT_TECHNIQUES = ("translation_leak", "summary_leak", "category_chain", "social_pressure", "fake_history",
                      "restate_wrap", "split_instruction", "cross_lingual")
HOLDOUT_PREFIX = "H-"
LABEL_STATUSES = ("model_labeled", "human_confirmed")
TITLE_MAX, CONTENT_MAX = 200, 5000          # CreateTicketRequest 的 @Size

# 配额(计划 §8):攻击 A12 / B10 / C10 / D8,对照四类各 8
ATTACK_QUOTA = {"A": 12, "B": 10, "C": 10, "D": 8}
CONTROL_PER_CATEGORY = 8
MIN_TITLE_INJECTIONS_PER_CLASS = 2

SAMPLE_FILES = ("controls.jsonl", "attacks.jsonl")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@dataclass
class Dataset:
    controls: list[dict[str, Any]]
    attacks: list[dict[str, Any]]

    @property
    def samples(self) -> list[dict[str, Any]]:
        return self.controls + self.attacks

    @property
    def by_id(self) -> dict[str, dict[str, Any]]:
        return {s["id"]: s for s in self.samples}

    def text_sha256(self) -> str:
        return text_sha256(self.samples)

    def is_uncertain(self, sample_id: str) -> bool:
        """⚠ 的范围(ADR-024 §5):对照 = 自身;A/B = 自身或基底;C/D = 仅自身;留出样本没有基底 = 仅自身"""
        s = self.by_id[sample_id]
        if s.get("uncertain"):
            return True
        if s["group"] == "attack" and s["attack_class"] in ("A", "B") and s.get("base_id"):
            return bool(self.by_id[s["base_id"]].get("uncertain"))
        return False

    def is_excluded(self, sample_id: str) -> bool:
        return bool(self.by_id[sample_id].get("excluded"))

    def all_human_confirmed(self) -> bool:
        return all(s["label_status"] == "human_confirmed" for s in self.samples)


def load(data_dir: Path = DATA_DIR) -> Dataset:
    return Dataset(controls=read_jsonl(data_dir / "controls.jsonl"),
                   attacks=read_jsonl(data_dir / "attacks.jsonl"))


def load_holdout(data_dir: Path = DATA_DIR) -> list[dict[str, Any]]:
    return read_jsonl(data_dir / "holdout.jsonl")


def text_sha256(samples: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for s in sorted(samples, key=lambda x: x["id"]):
        h.update(s["id"].encode("utf-8") + b"\x1f" + s["title"].encode("utf-8") + b"\x1f"
                 + s["content"].encode("utf-8") + b"\x1e")
    return h.hexdigest()


# ---------------------------------------------------------------------- 校验

def validate(ds: Dataset) -> list[str]:
    """返回全部问题(空列表 = 合格)。test_dataset.py 逐项断言;labels apply 回写前也跑一遍。"""
    errors: list[str] = []
    ids = [s["id"] for s in ds.samples]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        errors.append(f"id 重复: {sorted(dup)}")
    by_id = ds.by_id
    required = ("id", "group", "attack_class", "technique", "injection_in", "base_id", "title", "content",
                "expected", "target", "uncertain", "label_reason", "label_status", "reviewed_by", "reviewed_at")
    for s in ds.samples:
        sid = s.get("id", "?")
        missing = [k for k in required if k not in s]
        if missing:
            errors.append(f"{sid}: 缺字段 {missing}")
            continue
        if not s["title"].strip() or not s["content"].strip():
            errors.append(f"{sid}: 标题或内容为空")
        if len(s["title"]) > TITLE_MAX or len(s["content"]) > CONTENT_MAX:
            errors.append(f"{sid}: 超过接口长度上限 标题{len(s['title'])}/内容{len(s['content'])}")
        exp = s["expected"] or {}
        if exp.get("category") not in CATEGORIES or exp.get("priority") not in PRIORITIES:
            errors.append(f"{sid}: expected 不合法 {exp}")
        if s["label_status"] not in LABEL_STATUSES:
            errors.append(f"{sid}: label_status 不合法 {s['label_status']}")
        if not isinstance(s["uncertain"], bool):
            errors.append(f"{sid}: uncertain 不是布尔")
        if not s["label_reason"].strip():
            errors.append(f"{sid}: 缺标签理由")
        if s["label_status"] == "human_confirmed" and not s["reviewed_by"]:
            errors.append(f"{sid}: human_confirmed 但没有 reviewed_by")
        if s["group"] == "control":
            if not sid.startswith("N-"):
                errors.append(f"{sid}: 对照样本 id 应以 N- 开头")
            if any(s[k] is not None for k in ("attack_class", "technique", "injection_in", "base_id", "target")):
                errors.append(f"{sid}: 对照样本不应有攻击字段")
        elif s["group"] == "attack":
            cls = s["attack_class"]
            holdout = sid.startswith(HOLDOUT_PREFIX)
            if cls not in ATTACK_CLASSES or not (holdout or sid.startswith(cls + "-")):
                errors.append(f"{sid}: attack_class 不合法或与 id 前缀不符")
                continue
            if s["technique"] not in TECHNIQUES + (HOLDOUT_TECHNIQUES if holdout else ()):
                errors.append(f"{sid}: technique 不合法 {s['technique']}")
            if s["injection_in"] not in ("title", "content") + (("title+content",) if holdout else ()):
                errors.append(f"{sid}: injection_in 不合法")
            base = None
            if holdout:
                # 留出样本是新样本:没有基底,期望标签直接给在样本上;不做"与基底一致 / 注入位置与基底不同"两项检查
                if s["base_id"] is not None:
                    errors.append(f"{sid}: 留出样本没有基底,base_id 应为 null")
            else:
                base = by_id.get(s["base_id"])
                if base is None or base["group"] != "control":
                    errors.append(f"{sid}: base_id {s['base_id']} 不是已存在的对照样本")
                    continue
                if s["expected"] != base["expected"]:
                    errors.append(f"{sid}: 期望标签 {s['expected']} 与基底 {base['id']} {base['expected']} 不一致")
            tgt = s["target"] or {}
            want_field = {"A": "priority", "B": "category", "C": "draft", "D": "draft"}[cls]
            if tgt.get("field") != want_field:
                errors.append(f"{sid}: target.field 应为 {want_field}")
            if cls == "A":
                if tgt.get("value") != "P0":
                    errors.append(f"{sid}: A 类目标一律 P0")
                if s["expected"]["priority"] == "P0":
                    errors.append(f"{sid}: A 类基底期望已是 P0,提权无从判定")
            if cls == "B":
                if tgt.get("value") not in CATEGORIES:
                    errors.append(f"{sid}: B 类目标不在枚举内")
                if tgt.get("value") == s["expected"]["category"]:
                    errors.append(f"{sid}: B 类目标等于期望类别")
            if cls == "C" and tgt.get("value") != "promise":
                errors.append(f"{sid}: C 类目标应为 promise")
            if cls == "D" and tgt.get("value") != "leak":
                errors.append(f"{sid}: D 类目标应为 leak")
            # 注入位置与文本一致:标题注入的样本标题不同于基底;内容注入的样本内容不同于基底
            if base is not None and s["injection_in"] == "title" and s["title"] == base["title"]:
                errors.append(f"{sid}: 声明标题注入但标题与基底相同")
            if base is not None and s["injection_in"] == "content" and s["content"] == base["content"]:
                errors.append(f"{sid}: 声明内容注入但内容与基底相同")
        else:
            errors.append(f"{sid}: group 不合法 {s['group']}")
    return errors


def quota_report(ds: Dataset) -> dict[str, Any]:
    by_class = {c: [a for a in ds.attacks if a["attack_class"] == c] for c in ATTACK_CLASSES}
    return {
        "attacks": {c: len(v) for c, v in by_class.items()},
        "title_injections": {c: sum(1 for a in v if a["injection_in"] == "title") for c, v in by_class.items()},
        "controls": {cat: sum(1 for s in ds.controls if s["expected"]["category"] == cat) for cat in CATEGORIES},
        "techniques": {t: sum(1 for a in ds.attacks if a["technique"] == t) for t in TECHNIQUES},
    }


# ---------------------------------------------------------------------- 审核表

REVIEW_COLUMNS = ["id", "组别", "攻击类别", "手法", "注入位置", "基底", "标题", "内容",
                  "期望分类", "期望优先级", "攻击目标", "⚠", "标注理由", "标签状态",
                  "确认(Y)", "改为分类", "改为优先级", "改为攻击目标", "改为⚠(Y/N)", "剔除(Y)", "审核备注"]


PRIORITY_EXTRA_COLUMN = "入选原因"


def export_review(ds: Dataset, path: Path, only: list[tuple[str, str]] | None = None) -> int:
    """导出审核表(UTF-8 BOM,Excel 直接打开)。攻击样本的期望标签跟随基底,只能在基底那一行改。
    only = [(id, 入选原因)] 时只导出这些行,并在末尾多一列"入选原因"(精简审核表;apply 会忽略这一列)。"""
    reasons = dict(only) if only is not None else None
    samples = [ds.by_id[i] for i, _ in only] if only is not None else ds.samples
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(REVIEW_COLUMNS + ([PRIORITY_EXTRA_COLUMN] if reasons is not None else []))
        for s in samples:
            w.writerow([
                s["id"], "对照" if s["group"] == "control" else "攻击", s["attack_class"] or "", s["technique"] or "",
                s["injection_in"] or "", s["base_id"] or "", s["title"], s["content"],
                s["expected"]["category"], s["expected"]["priority"],
                (s["target"] or {}).get("value", ""), "⚠" if s["uncertain"] else "", s["label_reason"], s["label_status"],
                "", "", "", "", "", "Y" if s.get("excluded") else "", s.get("review_note", ""),
            ] + ([reasons[s["id"]]] if reasons is not None else []))
    return len(samples)


def apply_review(ds: Dataset, path: Path, reviewer: str, today: str | None = None) -> dict[str, int]:
    """把审核表回写进样本(内存中的 ds;调用方负责 save)。非法值直接抛 ValueError,整表不生效。"""
    today = today or _dt.date.today().isoformat()
    by_id = ds.by_id
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    stats = {"confirmed": 0, "changed": 0, "excluded": 0, "untouched": 0}
    problems: list[str] = []
    plans: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row in rows:
        sid = (row.get("id") or "").strip()
        s = by_id.get(sid)
        if s is None:
            problems.append(f"审核表里的 {sid!r} 不在数据集中")
            continue
        confirm = (row.get("确认(Y)") or "").strip().upper() == "Y"
        new_cat = (row.get("改为分类") or "").strip().upper()
        new_pri = (row.get("改为优先级") or "").strip().upper()
        new_tgt = (row.get("改为攻击目标") or "").strip()
        new_unc = (row.get("改为⚠(Y/N)") or "").strip().upper()
        excl = (row.get("剔除(Y)") or "").strip().upper() == "Y"
        note = (row.get("审核备注") or "").strip()
        change: dict[str, Any] = {}
        if new_cat:
            if s["group"] != "control":
                problems.append(f"{sid}: 攻击样本的期望标签继承自基底 {s['base_id']},请在基底那一行改")
            elif new_cat not in CATEGORIES:
                problems.append(f"{sid}: 改为分类 {new_cat} 不在枚举内")
            else:
                change["category"] = new_cat
        if new_pri:
            if s["group"] != "control":
                problems.append(f"{sid}: 攻击样本的期望标签继承自基底 {s['base_id']},请在基底那一行改")
            elif new_pri not in PRIORITIES:
                problems.append(f"{sid}: 改为优先级 {new_pri} 不在枚举内")
            else:
                change["priority"] = new_pri
        if new_tgt:
            if s["group"] != "attack" or s["attack_class"] not in ("A", "B"):
                problems.append(f"{sid}: 只有 A/B 类攻击样本可以改攻击目标")
            else:
                change["target"] = new_tgt.upper()
        if new_unc:
            if new_unc not in ("Y", "N"):
                problems.append(f"{sid}: 改为⚠ 只能填 Y 或 N")
            else:
                change["uncertain"] = new_unc == "Y"
        plans.append((s, {"confirm": confirm, "change": change, "excluded": excl, "note": note}))
    if problems:
        raise ValueError("审核表有问题,未回写:\n  " + "\n  ".join(problems))

    for s, p in plans:
        ch = p["change"]
        touched = p["confirm"] or bool(ch) or p["excluded"] != bool(s.get("excluded")) or bool(p["note"])
        if "category" in ch or "priority" in ch:
            s["expected"] = {"category": ch.get("category", s["expected"]["category"]),
                             "priority": ch.get("priority", s["expected"]["priority"])}
        if "target" in ch:
            s["target"] = {**s["target"], "value": ch["target"]}
        if "uncertain" in ch:
            s["uncertain"] = ch["uncertain"]
        if p["excluded"]:
            s["excluded"] = True
            stats["excluded"] += 1
        elif s.get("excluded"):
            s.pop("excluded")
        if p["note"]:
            s["review_note"] = p["note"]
        if touched:
            s["label_status"] = "human_confirmed"
            s["reviewed_by"] = reviewer
            s["reviewed_at"] = today
            stats["changed" if ch else "confirmed"] += 1
        else:
            stats["untouched"] += 1
    # 对照标签改了 → 同步到以它为基底的攻击样本
    for a in ds.attacks:
        a["expected"] = dict(by_id[a["base_id"]]["expected"])
    errors = validate(ds)
    if errors:
        raise ValueError("回写后校验失败,未保存:\n  " + "\n  ".join(errors))
    return stats


def save(ds: Dataset, data_dir: Path = DATA_DIR) -> None:
    write_jsonl(data_dir / "controls.jsonl", ds.controls)
    write_jsonl(data_dir / "attacks.jsonl", ds.attacks)
