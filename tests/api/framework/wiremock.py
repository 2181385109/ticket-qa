"""
WireMock 管理 API 客户端:看挡板"收到了什么",以及临时加桩。

用途:
  - 验证降级真的生效,不能只看服务的响应——还要看挡板那边:
    超时用例挡板收到了 1 个请求(服务确实发出去了,只是等不到);
    熔断期间挡板收到 0 个请求(服务根本没发)。
  - 临时桩(persistent=false)用完即删,不污染 ops/wiremock/mappings 里的文件桩。
"""
from __future__ import annotations

from typing import Any

import requests


class WireMock:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return f"{self.base_url}/__admin{path}"

    def healthy(self) -> bool:
        try:
            return self.session.get(self._url("/health"), timeout=3).ok
        except requests.RequestException:
            return False

    # ------------------------------------------------------------------ 请求日志

    def reset_requests(self) -> None:
        self.session.delete(self._url("/requests"), timeout=self.timeout).raise_for_status()

    def requests_to(self, url_path: str, body_contains: str | None = None) -> list[dict[str, Any]]:
        """挡板收到的、路径匹配的请求;body_contains 用来按标题里的 token 过滤到某一次调用"""
        r = self.session.post(self._url("/requests/find"), json={"method": "POST", "urlPath": url_path}, timeout=self.timeout)
        r.raise_for_status()
        found = r.json().get("requests", [])
        if body_contains is not None:
            found = [q for q in found if body_contains in (q.get("body") or "")]
        return found

    def count(self, url_path: str, body_contains: str | None = None) -> int:
        return len(self.requests_to(url_path, body_contains))

    # ------------------------------------------------------------------ 桩

    def mappings(self) -> list[dict[str, Any]]:
        r = self.session.get(self._url("/mappings"), timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("mappings", [])

    def add_stub(self, stub: dict[str, Any]) -> str:
        stub = {**stub, "persistent": False}
        r = self.session.post(self._url("/mappings"), json=stub, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["id"]

    def delete_stub(self, stub_id: str) -> None:
        self.session.delete(self._url(f"/mappings/{stub_id}"), timeout=self.timeout)

    def reset_to_files(self) -> None:
        """丢掉所有临时桩,恢复成 mappings/ 目录里的文件桩"""
        self.session.post(self._url("/mappings/reset"), timeout=self.timeout).raise_for_status()
