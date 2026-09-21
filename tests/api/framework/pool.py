"""
HikariCP 连接池预热(KI-010 / KI-016 第 16 条)。

压测记录证明:并发用例的结果(能同时进库的线程数)= 那一刻池里已有的连接数 + 1,而池会在 10 分钟空闲后
从 20 缩回 2。所以并发用例跑之前先把池撑满,让 CI 和本地在同一个起点上;用例本身仍只断言
"≥2 个 200 即失败",不断言具体的 409 分布。

做法:max-pool-size + 5 个线程同时**创建工单**——Hikari 只在有线程排队等连接时才异步补连接,
而只读列表在空库上不到 1 ms 就把连接还回去了,根本排不起队;创建一张单要持有连接 30~40 ms(插入 + 审计 + fsync),
25 个并发创建能让 20 条连接同时忙、5 个线程排队,几轮就把池撑到上限。造出来的工单随后硬删(给了 db 的话)。
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .db import Db
from .metrics import Metrics
from .users import Users


def pool_size(metrics: Metrics) -> tuple[float, float]:
    """(total, max)"""
    snap = metrics.snapshot()
    return Metrics._match(snap, "hikaricp_connections", {}), Metrics._match(snap, "hikaricp_connections_max", {})


def warm_pool(base_url: str, metrics: Metrics, db: Db | None = None, rounds: int = 6,
              timeout: float = 15.0) -> tuple[float, float]:
    """返回预热后的 (total, max)。达到 max 即停;最多 rounds 轮;造的工单结束时硬删。"""
    total, maximum = pool_size(metrics)
    created: list[int] = []
    lock = threading.Lock()
    try:
        for _ in range(rounds):
            if maximum and total >= maximum:
                break
            n = int(maximum or 20) + 5
            barrier = threading.Barrier(n)

            def hit(i: int) -> int:
                s = requests.Session()
                barrier.wait(timeout=10)
                r = s.post(f"{base_url}/api/tickets",
                           data=b'{"title":"pool warm-up","content":"warm","customerId":1}',
                           headers={"X-User-Id": str(Users.ADMIN.id), "Content-Type": "application/json"},
                           timeout=timeout)
                if r.status_code == 201:
                    with lock:
                        created.append(int(r.json()["data"]["id"]))
                return r.status_code

            with ThreadPoolExecutor(max_workers=n) as ex:
                list(ex.map(hit, range(n)))
            time.sleep(1.0)     # 给 Hikari 的后台线程时间建连并登记进指标
            total, maximum = pool_size(metrics)
    finally:
        if db is not None and created:
            db.hard_delete_tickets(created)
    return total, maximum
