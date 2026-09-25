"""C / D 类判定用的文本归一化(ADR-024 判定口径 §4):NFKC → 小写 → 删除全部空白。

逐字符归一化并保留"归一化后第 i 个字符来自原文第几个字符"的映射,这样命中位置能换算回原文、截取原文上下文。
对中文和 ASCII,逐字符 NFKC 与整串 NFKC 结果一致(本项目文本里没有组合附加符号序列)。
"""
from __future__ import annotations

import unicodedata


def normalize_with_map(text: str | None) -> tuple[str, list[int]]:
    if not text:
        return "", []
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).lower():
            if c.isspace():
                continue
            out.append(c)
            index.append(i)
    return "".join(out), index


def normalize(text: str | None) -> str:
    return normalize_with_map(text)[0]
