"""C / D 类判定用的文本归一化(ADR-024 判定口径 §4):NFKC → 小写 → 删除全部空白。"""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    if not text:
        return ""
    return _WS.sub("", unicodedata.normalize("NFKC", text).lower())
