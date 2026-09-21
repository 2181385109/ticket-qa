"""
HikariCP 连接池预热(KI-010 / KI-016 第 16 条)。

压测记录证明:并发用例的结果(能同时进库的线程数)= 那一刻池里已有的连接数 + 1,而池会在 10 分钟空闲后
从 20 缩回 2。所以并发用例跑之前先把池撑满,让 CI 和本地在同一个起点上;用例本身仍只断言
"≥2 个 200 即失败",不断言具体的 409 分布。

做法:max-pool-size + 5 个线程**持续**创建工单 burst_seconds 秒(不是一次齐射)。Hikari 只在有线程排队等连接时
才补连接,而且补连接是单线程、逐条建的(每条几十毫秒,含 TCP + 鉴权),建完一条再看一眼"还有没有人在等"——
没人等就不再建。齐射 25 个请求在慢机器(Windows ↔ WSL,一次创建几百毫秒)上排队时间足够长,几轮就满;
在 GitHub runner 上一次创建只要 ~15 ms,齐射结束时第一条连接还没建好,每轮只能涨 1 条,6 轮到不了 20
(开源仓库第三次 CI:预热停在 17,四条并发用例在 fixture 上 error)。持续打 2 秒让"有人在等"这个条件贯穿整个
建连过程,建连就会一条接一条地进行,快机器慢机器都在一轮内到上限。中途每 0.25 s 看一次指标,到上限立即停,
不多造;造出来的工单随后硬删(给了 db 的话)。只读列表不能用:空库上不到 1 ms 就把连接还回去了,排不起队。
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


def warm_pool(base_url: str, metrics: Metrics, db: Db | None = None, rounds: int = 3,
              timeout: float = 15.0, burst_seconds: float = 2.0) -> tuple[float, float]:
    """返回预热后的 (total, max)。达到 max 即停;最多 rounds 轮,每轮持续压 burst_seconds 秒;造的工单结束时硬删。"""
    total, maximum = pool_size(metrics)
    created: list[int] = []
    lock = threading.Lock()
    halt = threading.Event()

    def hit_loop(_: int) -> None:
        s = requests.Session()
        while not halt.is_set():
            r = s.post(f"{base_url}/api/tickets",
                       data=b'{"title":"pool warm-up","content":"warm","customerId":1}',
                       headers={"X-User-Id": str(Users.ADMIN.id), "Content-Type": "application/json"},
                       timeout=timeout)
            if r.status_code == 201:
                with lock:
                    created.append(int(r.json()["data"]["id"]))

    try:
        for _ in range(rounds):
            if maximum and total >= maximum:
                break
            n = int(maximum or 20) + 5
            halt.clear()
            with ThreadPoolExecutor(max_workers=n) as ex:
                futures = [ex.submit(hit_loop, i) for i in range(n)]
                deadline = time.monotonic() + burst_seconds
                while time.monotonic() < deadline:
                    time.sleep(0.25)
                    total, maximum = pool_size(metrics)
                    if maximum and total >= maximum:
                        break
                halt.set()
                for f in futures:
                    f.result()
            time.sleep(0.5)     # 给 Hikari 的后台线程时间把最后一条登记进指标
            total, maximum = pool_size(metrics)
    finally:
        if db is not None and created:
            db.hard_delete_tickets(created)
    return total, maximum
