"""
ApiClient:所有 HTTP 调用的唯一出口。

- 统一鉴权:构造时给 user(User 或 int),每个请求自动带 X-User-Id;as_user() 派生一个换身份的客户端
- 统一日志:每个请求把 请求行 / 请求体 / 响应状态 / 响应体 / 耗时 作为 Allure 附件挂到当前 step
- 返回 ApiResponse,而不是 requests.Response,断言从 resp.expect 开始
- 业务接口的薄封装(create_ticket / grab / transit ...)只负责拼 URL 和 body,不做断言——
  断言是用例的事,封装层断了状态码,想测"非法请求返回 409"就得绕开封装
"""
from __future__ import annotations

import json
import time
from typing import Any

import allure
import requests

from .response import ApiResponse
from .users import User


class ApiClient:
    def __init__(self, base_url: str, user: User | int | None = None, timeout: float = 15.0,
                 session: requests.Session | None = None, attach: bool = True):
        self.base_url = base_url.rstrip("/")
        self.user_id = user.id if isinstance(user, User) else user
        self.timeout = timeout
        self.session = session or requests.Session()
        # 容量类用例一条用例发几千个请求,逐个挂 Allure 附件会把结果目录撑到几万个文件——它们用 attach=False
        self.attach = attach

    def as_user(self, user: User | int | None) -> "ApiClient":
        return ApiClient(self.base_url, user, self.timeout, self.session, self.attach)

    # ------------------------------------------------------------------ 底层

    def request(self, method: str, path: str, *, json_body: Any = None, params: dict | None = None,
                headers: dict | None = None, files: dict | None = None, data: Any = None,
                raw_body: bytes | None = None, user: User | int | None = "inherit",
                timeout: float | None = None) -> ApiResponse:
        url = path if path.startswith("http") else self.base_url + path
        hdrs: dict[str, str] = {}
        uid = self.user_id if user == "inherit" else (user.id if isinstance(user, User) else user)
        if uid is not None:
            hdrs["X-User-Id"] = str(uid)
        if headers:
            hdrs.update(headers)

        kwargs: dict[str, Any] = dict(params=params, headers=hdrs, timeout=timeout or self.timeout)
        if raw_body is not None:
            kwargs["data"] = raw_body
        elif files is not None:
            kwargs["files"] = files
            if data is not None:
                kwargs["data"] = data
        elif json_body is not None:
            # 自己序列化以保留中文(requests 的 json= 会 ensure_ascii,服务端能读但附件里不好看)
            kwargs["data"] = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
        elif data is not None:
            kwargs["data"] = data

        summary = f"{method} {path} user={uid}"
        t0 = time.perf_counter()
        raw = self.session.request(method, url, **kwargs)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        resp = ApiResponse(raw, elapsed_ms, summary)
        if self.attach:
            self._attach(method, url, hdrs, json_body, params, resp)
        return resp

    @staticmethod
    def _attach(method: str, url: str, headers: dict, body: Any, params: dict | None, resp: ApiResponse) -> None:
        req_lines = [f"{method} {url}"]
        if params:
            req_lines.append(f"params: {params}")
        req_lines.append("headers: " + json.dumps(headers, ensure_ascii=False))
        if body is not None:
            req_lines.append("body: " + json.dumps(body, ensure_ascii=False, indent=2))
        resp_body = resp.text if resp.json is None else json.dumps(resp.json, ensure_ascii=False, indent=2)
        allure.attach("\n".join(req_lines), name=f"request {method} {url.split('/api/')[-1][:60]}",
                      attachment_type=allure.attachment_type.TEXT)
        allure.attach(f"HTTP {resp.status}  {resp.elapsed_ms}ms  X-Trace-Id={resp.trace_id}\n\n{resp_body[:4000]}",
                      name=f"response {resp.status}", attachment_type=allure.attachment_type.TEXT)

    def get(self, path: str, **kw) -> ApiResponse:
        return self.request("GET", path, **kw)

    def post(self, path: str, json_body: Any = None, **kw) -> ApiResponse:
        return self.request("POST", path, json_body=json_body, **kw)

    def put(self, path: str, json_body: Any = None, **kw) -> ApiResponse:
        return self.request("PUT", path, json_body=json_body, **kw)

    def delete(self, path: str, **kw) -> ApiResponse:
        return self.request("DELETE", path, **kw)

    # ------------------------------------------------------------------ 业务接口薄封装(README §5 接口清单)

    def health(self) -> ApiResponse:
        return self.get("/actuator/health", user=None)

    def prometheus(self) -> ApiResponse:
        return self.get("/actuator/prometheus", user=None)

    def me(self) -> ApiResponse:
        return self.get("/api/agents/me")

    def create_ticket(self, title: str, content: str, customer_id: int = 1001, group_id: int | None = None,
                      **extra) -> ApiResponse:
        body: dict[str, Any] = {"title": title, "content": content, "customerId": customer_id}
        if group_id is not None:
            body["groupId"] = group_id
        body.update(extra)
        return self.post("/api/tickets", body)

    def create_ticket_raw(self, body: Any) -> ApiResponse:
        """不做任何字段整理,给参数校验 / 注入用例用"""
        return self.post("/api/tickets", body)

    def get_ticket(self, ticket_id: Any) -> ApiResponse:
        return self.get(f"/api/tickets/{ticket_id}")

    def list_tickets(self, **params) -> ApiResponse:
        return self.get("/api/tickets", params=params or None)

    def update_ticket(self, ticket_id: Any, title: str, content: str) -> ApiResponse:
        return self.put(f"/api/tickets/{ticket_id}", {"title": title, "content": content})

    def delete_ticket(self, ticket_id: Any) -> ApiResponse:
        return self.delete(f"/api/tickets/{ticket_id}")

    def transit(self, ticket_id: Any, target: str, assignee_id: int | None = None, remark: str | None = None) -> ApiResponse:
        body: dict[str, Any] = {"target": target}
        if assignee_id is not None:
            body["assigneeId"] = assignee_id
        if remark is not None:
            body["remark"] = remark
        return self.post(f"/api/tickets/{ticket_id}/transitions", body)

    def grab(self, ticket_id: Any) -> ApiResponse:
        return self.post(f"/api/tickets/{ticket_id}/grab")

    def assign(self, ticket_id: Any, assignee_id: Any, remark: str | None = None) -> ApiResponse:
        body: dict[str, Any] = {"assigneeId": assignee_id}
        if remark is not None:
            body["remark"] = remark
        return self.post(f"/api/tickets/{ticket_id}/assign", body)

    def audit_logs(self, ticket_id: Any) -> ApiResponse:
        return self.get(f"/api/tickets/{ticket_id}/audit-logs")

    def reply_draft(self, ticket_id: Any) -> ApiResponse:
        return self.post(f"/api/tickets/{ticket_id}/reply-draft")

    def upload(self, ticket_id: Any, filename: str, content: bytes, content_type: str | None) -> ApiResponse:
        """multipart 字段名 file。content_type=None 表示不声明 Content-Type(requests 会省略该 part 的类型头)。"""
        files = {"file": (filename, content, content_type) if content_type else (filename, content)}
        return self.request("POST", f"/api/tickets/{ticket_id}/attachments", files=files)

    def list_attachments(self, ticket_id: Any) -> ApiResponse:
        return self.get(f"/api/tickets/{ticket_id}/attachments")

    def sla_scan(self) -> ApiResponse:
        return self.post("/api/admin/sla/scan")
