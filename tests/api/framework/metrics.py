"""
Prometheus 文本格式解析 + 差值断言。

指标是 LLM 路径和 MQ 路径的第二类旁路证据(第一类是库表)。用法:
    before = metrics.snapshot()
    ... 触发行为 ...
    assert metrics.delta(before, "llm_fallback_total", scene="CLASSIFY", reason="TIMEOUT") == 1

为什么按差值而不是绝对值:服务从启动起累计,绝对值取决于之前跑过什么;差值只和本用例有关。
"""
from __future__ import annotations

import re
from typing import Any

import requests

_LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([-+]?[0-9.eE+NaInf]+)')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')

Key = tuple[str, frozenset[tuple[str, str]]]


class Metrics:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.url = base_url.rstrip("/") + "/actuator/prometheus"
        self.timeout = timeout

    def snapshot(self) -> dict[Key, float]:
        text = requests.get(self.url, timeout=self.timeout).text
        out: dict[Key, float] = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            m = _LINE.match(line)
            if not m:
                continue
            name, labels, value = m.group(1), m.group(2) or "", m.group(3)
            pairs = frozenset((k, v) for k, v in _LABEL.findall(labels))
            try:
                out[(name, pairs)] = float(value)
            except ValueError:
                continue
        return out

    @staticmethod
    def _match(snap: dict[Key, float], name: str, labels: dict[str, str]) -> float:
        """同名、且给定标签都匹配的序列求和(不给标签就是全部序列之和)"""
        want = set(labels.items())
        total = 0.0
        for (n, pairs), v in snap.items():
            if n == name and want <= set(pairs):
                total += v
        return total

    def value(self, name: str, **labels: str) -> float:
        return self._match(self.snapshot(), name, labels)

    def delta(self, before: dict[Key, float], name: str, **labels: str) -> float:
        return self._match(self.snapshot(), name, labels) - self._match(before, name, labels)

    def names(self) -> set[str]:
        return {n for (n, _) in self.snapshot()}
