"""
并发触发:N 个线程在同一个栅栏上等齐、同时发请求,返回全部响应。

和 JMeter 集合点是一个意思(tests/perf/grab_race.jmx),放进 pytest 是为了让"并发正确性"进入每次 CI:
JMeter 那份是复现和定位用的,这份是回归门禁。

两个注意点:
  - 每个线程用**独立的 requests.Session**:同一个 Session 在多线程下会复用同一条连接,请求会被串行化,
    "同时发"就成了假的;
  - 用 threading.Barrier 而不是简单地 submit N 个任务:线程池的线程启动有先后,不等齐就发,
    前两个请求的间隔可能大于一次抢单事务(~13 ms),竞态窗口就错过了。
"""
from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Sequence

import allure
import requests

from .client import ApiClient
from .response import ApiResponse
from .users import User


def fire_concurrently(base_url: str, users: Sequence[User | int], fn: Callable[[ApiClient, int], ApiResponse],
                      timeout: float = 30.0) -> list[ApiResponse]:
    """users[i] 作为第 i 个线程的身份;fn(client, i) 发一个请求。全部线程在栅栏上等齐后同时发。"""
    n = len(users)
    barrier = threading.Barrier(n)
    results: list[ApiResponse | None] = [None] * n
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        client = ApiClient(base_url, users[i], timeout, session=requests.Session())
        try:
            barrier.wait(timeout=10)
            results[i] = fn(client, i)
        except BaseException as e:      # noqa: BLE001 —— 线程里的异常要带回主线程
            errors.append(e)

    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(worker, range(n)))
    if errors:
        raise AssertionError(f"{len(errors)} 个并发线程异常: {errors[0]!r}")
    return [r for r in results if r is not None]


def summarize(responses: list[ApiResponse], name: str = "并发结果") -> Counter:
    """按 (HTTP, code) 计数并挂成 Allure 附件,返回 Counter"""
    counter = Counter((r.status, r.code) for r in responses)
    lines = [f"HTTP {s} code {c}: {n}" for (s, c), n in sorted(counter.items())]
    lines += ["", *[f"{r.request_summary} -> {r.status}/{r.code} {r.elapsed_ms}ms trace={r.trace_id}" for r in responses]]
    allure.attach("\n".join(lines), name=name, attachment_type=allure.attachment_type.TEXT)
    return counter


def successes(responses: list[ApiResponse]) -> list[ApiResponse]:
    return [r for r in responses if r.status == 200 and r.code == 0]


def blast(base_url: str, user: User | int, threads: int, seconds: float,
          fn: Callable[[ApiClient, int], ApiResponse], timeout: float = 30.0) -> list[ApiResponse]:
    """N 个线程各自循环调用 fn 直到时间到(容量类用例用):返回全部响应。每线程独立 Session。"""
    import time
    deadline = time.monotonic() + seconds
    out: list[list[ApiResponse]] = [[] for _ in range(threads)]

    def worker(i: int) -> None:
        client = ApiClient(base_url, user, timeout, session=requests.Session(), attach=False)
        while time.monotonic() < deadline:
            out[i].append(fn(client, i))

    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(worker, range(threads)))
    return [r for lst in out for r in lst]
