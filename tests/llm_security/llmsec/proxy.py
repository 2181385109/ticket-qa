"""
录制代理:服务 → 本代理 → 上游 LLM(OpenAI 兼容协议)。

为什么要它:第一阶段不许改服务代码,而 llm_call_log 没有原始输出和 system_fingerprint。把服务的 LLM_BASE_URL 指到这里,
代理原样转发、原样回传,同时记下每次调用的完整请求体(提示词)、响应 model、system_fingerprint、usage、原始输出、耗时。
第二阶段测到的也是 Java 里真实的防御代码,而不是 Python 复制品。

安全:Authorization 头只转发,不落盘、不打印;记录里没有任何请求头。
只用标准库 http.server + requests(已在 tests/requirements.txt)。
"""
from __future__ import annotations

import datetime as _dt
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests

FORWARD_HEADERS = ("authorization", "content-type", "accept")
TEXT_LIMIT = 4000


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def summarize(method: str, path: str, req_body: bytes, status: int | None, resp_body: bytes,
              latency_ms: int, error: str | None) -> dict[str, Any]:
    """把一次转发整理成记录(纯函数,离线可测)"""
    rec: dict[str, Any] = {"t_utc": _utc_now(), "method": method, "path": path, "status": status,
                           "latency_ms": latency_ms, "error": error}
    try:
        req = json.loads(req_body.decode("utf-8")) if req_body else {}
    except ValueError:
        req = {}
    rec["request"] = {k: req.get(k) for k in ("model", "temperature", "max_tokens", "response_format", "messages")
                      if k in req}
    rec["request_model"] = req.get("model")
    try:
        resp = json.loads(resp_body.decode("utf-8")) if resp_body else None
    except ValueError:
        resp = None
    if isinstance(resp, dict):
        rec["response_model"] = resp.get("model")
        rec["system_fingerprint"] = resp.get("system_fingerprint")
        rec["usage"] = resp.get("usage")
        choice = (resp.get("choices") or [{}])[0] if isinstance(resp.get("choices"), list) else {}
        msg = choice.get("message") or {}
        rec["content"] = msg.get("content")
        rec["finish_reason"] = choice.get("finish_reason")
        if "error" in resp:
            rec["error_body"] = json.dumps(resp["error"], ensure_ascii=False)[:TEXT_LIMIT]
    else:
        rec.update(response_model=None, system_fingerprint=None, usage=None, content=None, finish_reason=None)
        if resp_body:
            rec["response_text"] = resp_body.decode("utf-8", "replace")[:TEXT_LIMIT]
    return rec


class RecordingProxy:
    def __init__(self, upstream_base: str, host: str = "127.0.0.1", port: int = 18090, timeout: float = 120.0):
        self.upstream_base = upstream_base.rstrip("/")
        self.host, self.port, self.timeout = host, port, timeout
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ 生命周期

    def start(self) -> "RecordingProxy":
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _read_body(self) -> bytes:
                if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                    chunks = []
                    while True:
                        size = int(self.rfile.readline().strip() or b"0", 16)
                        if size == 0:
                            self.rfile.readline()
                            break
                        chunks.append(self.rfile.read(size))
                        self.rfile.readline()
                    return b"".join(chunks)
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length else b""

            def _handle(self) -> None:
                body = self._read_body()
                headers = {k: v for k, v in self.headers.items() if k.lower() in FORWARD_HEADERS}
                headers["Accept-Encoding"] = "identity"
                t0 = time.perf_counter()
                status, resp_body, ctype, error = None, b"", "application/json", None
                try:
                    r = proxy._session.request(self.command, proxy.upstream_base + self.path, data=body or None,
                                               headers=headers, timeout=proxy.timeout)
                    status, resp_body = r.status_code, r.content
                    ctype = r.headers.get("Content-Type", ctype)
                except requests.RequestException as e:
                    error = f"{type(e).__name__}: {str(e)[:300]}"
                latency = int((time.perf_counter() - t0) * 1000)
                proxy._add(summarize(self.command, self.path, body, status, resp_body, latency, error))
                out_status = status if status is not None else 502
                if status is None:
                    resp_body = json.dumps({"error": {"message": "recording proxy: upstream unreachable"}}).encode()
                self.send_response(out_status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            do_POST = _handle
            do_GET = _handle

            def log_message(self, fmt: str, *args: Any) -> None:     # 不往控制台刷请求行
                return

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="recording-proxy", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ------------------------------------------------------------------ 记录

    def _add(self, rec: dict[str, Any]) -> None:
        with self._lock:
            self._records.append(rec)

    def drain(self) -> list[dict[str, Any]]:
        """取走并清空当前积累的记录。runner 串行调用:每次接口调用前后各 drain 一次,中间的就是这一次的上游调用"""
        with self._lock:
            out, self._records = self._records, []
        return out
