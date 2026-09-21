"""
响应对象 + 断言 DSL。

ApiResponse:把 requests.Response 包一层,直接暴露服务的统一返回体 {code, message, data, traceId}。
Expect:链式断言。每一步失败都抛 AssertionError,错误信息里带请求摘要和响应体,
       不用再去翻日志;每一步同时记一个 Allure step,报告里能看到断言链。

为什么自己写而不用 jsonschema / HttpRunner 的 validate 列表(ADR-012):
  - 这个服务的错误码、traceId、degraded 字段是自己定的契约,DSL 也应该长成契约的样子:
    resp.expect.status(201).code(0).data("category").is_in(CATEGORIES)
  - 断言失败时要能自动把响应体和 traceId 打进错误信息——这是排查效率的核心,通用框架给不了。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Iterable

import allure
import requests


class ApiResponse:
    def __init__(self, raw: requests.Response, elapsed_ms: int, request_summary: str):
        self.raw = raw
        self.elapsed_ms = elapsed_ms
        self.request_summary = request_summary
        self._json: Any = None
        self._json_parsed = False

    # ---- 基本访问 ----

    @property
    def status(self) -> int:
        return self.raw.status_code

    @property
    def text(self) -> str:
        return self.raw.text

    @property
    def json(self) -> Any:
        if not self._json_parsed:
            self._json_parsed = True
            try:
                self._json = self.raw.json()
            except ValueError:
                self._json = None
        return self._json

    @property
    def is_envelope(self) -> bool:
        return isinstance(self.json, dict) and "code" in self.json

    @property
    def code(self) -> int | None:
        return self.json.get("code") if self.is_envelope else None

    @property
    def message(self) -> str | None:
        return self.json.get("message") if self.is_envelope else None

    @property
    def data(self) -> Any:
        return self.json.get("data") if self.is_envelope else self.json

    @property
    def trace_id(self) -> str | None:
        return self.raw.headers.get("X-Trace-Id")

    def header(self, name: str) -> str | None:
        return self.raw.headers.get(name)

    def path(self, dotted: str, default: Any = None) -> Any:
        """按点路径取值:'data.records.0.groupId'。取不到返回 default(不抛)。"""
        cur = self.json
        for part in dotted.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part, default)
            elif isinstance(cur, list) and part.isdigit():
                idx = int(part)
                cur = cur[idx] if idx < len(cur) else default
            else:
                return default
            if cur is default:
                return default
        return cur

    def summary(self, limit: int = 600) -> str:
        body = self.text if self.json is None else json.dumps(self.json, ensure_ascii=False)
        if len(body) > limit:
            body = body[:limit] + "..."
        return f"{self.request_summary} -> HTTP {self.status} code={self.code} {self.elapsed_ms}ms traceId={self.trace_id}\n  body: {body}"

    @property
    def expect(self) -> "Expect":
        return Expect(self)

    def __repr__(self) -> str:
        return f"<ApiResponse {self.summary(200)}>"


class _Field:
    """Expect.data(...) / Expect.body(...) 返回的字段断言器,断完回到 Expect 继续链。"""

    def __init__(self, parent: "Expect", label: str, value: Any):
        self.parent = parent
        self.label = label
        self.value = value

    def _check(self, ok: bool, what: str) -> "Expect":
        return self.parent._record(ok, f"{self.label} {what} (actual={self.value!r})")

    def eq(self, expected: Any) -> "Expect":
        return self._check(self.value == expected, f"== {expected!r}")

    def ne(self, other: Any) -> "Expect":
        return self._check(self.value != other, f"!= {other!r}")

    def is_in(self, options: Iterable[Any]) -> "Expect":
        options = list(options)
        return self._check(self.value in options, f"in {options!r}")

    def not_in(self, options: Iterable[Any]) -> "Expect":
        options = list(options)
        return self._check(self.value not in options, f"not in {options!r}")

    def is_none(self) -> "Expect":
        return self._check(self.value is None, "is None")

    def not_none(self) -> "Expect":
        return self._check(self.value is not None, "is not None")

    def truthy(self) -> "Expect":
        return self._check(bool(self.value), "is truthy")

    def falsy(self) -> "Expect":
        return self._check(not self.value, "is falsy")

    def contains(self, needle: Any) -> "Expect":
        try:
            ok = needle in self.value
        except TypeError:
            ok = False
        return self._check(ok, f"contains {needle!r}")

    def not_contains(self, needle: Any) -> "Expect":
        try:
            ok = needle not in self.value
        except TypeError:
            ok = True
        return self._check(ok, f"not contains {needle!r}")

    def matches(self, pattern: str) -> "Expect":
        ok = isinstance(self.value, str) and re.fullmatch(pattern, self.value) is not None
        return self._check(ok, f"matches /{pattern}/")

    def gt(self, n: Any) -> "Expect":
        return self._check(self.value is not None and self.value > n, f"> {n!r}")

    def ge(self, n: Any) -> "Expect":
        return self._check(self.value is not None and self.value >= n, f">= {n!r}")

    def lt(self, n: Any) -> "Expect":
        return self._check(self.value is not None and self.value < n, f"< {n!r}")

    def length(self, n: int) -> "Expect":
        actual = len(self.value) if self.value is not None else None
        return self.parent._record(actual == n, f"len({self.label}) == {n} (actual={actual})")

    def satisfies(self, predicate: Callable[[Any], bool], desc: str) -> "Expect":
        return self._check(bool(predicate(self.value)), desc)

    def each(self, predicate: Callable[[Any], bool], desc: str) -> "Expect":
        items = self.value or []
        bad = [i for i in items if not predicate(i)]
        return self.parent._record(not bad, f"every item of {self.label} {desc} (violations={bad[:3]!r})")


class Expect:
    def __init__(self, resp: ApiResponse):
        self.resp = resp

    # ---- 内部 ----

    def _record(self, ok: bool, desc: str) -> "Expect":
        with allure.step(("✓ " if ok else "✗ ") + desc):
            if not ok:
                raise AssertionError(f"断言失败: {desc}\n{self.resp.summary()}")
        return self

    # ---- HTTP / 信封 ----

    def status(self, expected: int) -> "Expect":
        return self._record(self.resp.status == expected, f"HTTP status == {expected} (actual={self.resp.status})")

    def code(self, expected: int) -> "Expect":
        return self._record(self.resp.code == expected, f"biz code == {expected} (actual={self.resp.code})")

    def ok(self) -> "Expect":
        """200 + code 0"""
        return self.status(200).code(0)

    def created(self) -> "Expect":
        return self.status(201).code(0)

    def error(self, http: int, biz: int) -> "Expect":
        """错误响应的完整契约:HTTP 状态 + 业务码 + data 为空 + 有 traceId。
        约定:业务码前三位等于 HTTP 状态(ErrorCode.java)。"""
        return (self.status(http).code(biz)
                ._record(biz // 100 == http, f"错误码 {biz} 的前三位 == HTTP {http}")
                ._record(self.resp.data is None, "data is null on error")
                .has_trace_id())

    def has_trace_id(self) -> "Expect":
        body_tid = self.resp.path("traceId")
        header_tid = self.resp.trace_id
        return self._record(bool(header_tid) and body_tid == header_tid,
                            f"traceId in body == X-Trace-Id header (body={body_tid!r}, header={header_tid!r})")

    def envelope(self) -> "Expect":
        """统一返回体四个键齐全"""
        keys = set(self.resp.json.keys()) if isinstance(self.resp.json, dict) else set()
        return self._record({"code", "message", "traceId"} <= keys, f"envelope keys ⊇ {{code,message,traceId}} (actual={sorted(keys)})")

    def header(self, name: str) -> _Field:
        return _Field(self, f"header[{name}]", self.resp.header(name))

    # ---- 字段 ----

    def data(self, dotted: str = "") -> _Field:
        """相对 data 的点路径;空串表示 data 本身"""
        value = self.resp.data if not dotted else self.resp.path("data." + dotted)
        return _Field(self, f"data.{dotted}" if dotted else "data", value)

    def body(self, dotted: str) -> _Field:
        return _Field(self, dotted, self.resp.path(dotted))

    def has_keys(self, *keys: str) -> "Expect":
        d = self.resp.data if isinstance(self.resp.data, dict) else {}
        missing = [k for k in keys if k not in d]
        return self._record(not missing, f"data has keys {list(keys)} (missing={missing})")

    def lacks_keys(self, *keys: str) -> "Expect":
        d = self.resp.data if isinstance(self.resp.data, dict) else {}
        present = [k for k in keys if k in d]
        return self._record(not present, f"data lacks keys {list(keys)} (present={present})")

    # ---- 耗时 ----

    def elapsed_lt(self, ms: int) -> "Expect":
        return self._record(self.resp.elapsed_ms < ms, f"elapsed < {ms}ms (actual={self.resp.elapsed_ms}ms)")

    def elapsed_ge(self, ms: int) -> "Expect":
        return self._record(self.resp.elapsed_ms >= ms, f"elapsed >= {ms}ms (actual={self.resp.elapsed_ms}ms)")

    # ---- 逃生口 ----

    def that(self, predicate: Callable[[ApiResponse], bool], desc: str) -> "Expect":
        return self._record(bool(predicate(self.resp)), desc)
