"""
轮询等待。异步链路(MQ 消费、熔断恢复)没法同步断言,只能"等到条件成立或超时"。
超时抛 AssertionError 并带上最后一次观察值,不用 sleep(固定秒数)猜。
"""
from __future__ import annotations

import time
from typing import Any, Callable


def wait_until(probe: Callable[[], Any], ok: Callable[[Any], bool], *, timeout: float, interval: float = 0.3,
               what: str = "条件成立") -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while True:
        last = probe()
        if ok(last):
            return last
        if time.monotonic() >= deadline:
            raise AssertionError(f"等待 {what} 超时({timeout}s),最后观察值: {last!r}")
        time.sleep(interval)
