"""
容量与积压——压测记录 §5 里"顺带发现"的三个缺口,变成有数字断言的用例(docs/test-design/08 §3)。

  KI-012 MQ 消费 ≈190 条/s,生产 > 20 线程即积压     → 生产 > 消费时队列深度上升、停止后多久清空、一条不丢
  KI-013 SLA 调度器 100 张/30 s,到期高峰积压数小时   → 一批同时到期的工单要扫几轮、每轮不超过 batch、无一重复升级
  第 13 条 消费者与 HTTP 争同一个 HikariCP 池        → 池被打满(pending>0)期间消费不能归零,停止后积压能清完

这些用例断言的是**当前配置下的容量契约**(积压能在预算内清完、不丢、不重复),不是"没有积压"——
积压本身是记录在案的容量特性(KI-012 / KI-013),真要消掉得改配置(消费者并发、独立连接池、批大小),那是另一条 ADR。
数字全部挂进 Allure:每次 CI 都会留下一份"这台机器上的消费速率 / 升级吞吐"。
"""
import math
import threading
import time

import allure
import pytest

from framework.concurrency import blast
from framework.users import Users
from framework.waits import wait_until

pytestmark = [allure.feature("容量"), pytest.mark.capacity, pytest.mark.slow, pytest.mark.db, pytest.mark.mq]


def _track_all(tickets, responses):
    """把 blast 造出来的工单全部登记到工厂,用例结束统一硬删"""
    ids = [r.data["id"] for r in responses if r.status == 201]
    tickets.created_ids.extend(ids)
    return ids


def create_many(tickets, config, n: int, threads: int, title: str) -> list[int]:
    """并发造 n 张 PENDING 单(group 1),全部登记到工厂"""
    from concurrent.futures import ThreadPoolExecutor
    from framework.client import ApiClient
    import requests

    def one(i: int) -> int:
        client = ApiClient(config.base_url, Users.ADMIN, 30, session=requests.Session(), attach=False)
        r = client.create_ticket(f"{title} {i}", "x", group_id=1)
        assert r.status == 201, r.summary()
        return int(r.data["id"])

    with ThreadPoolExecutor(max_workers=threads) as ex:
        ids = list(ex.map(one, range(n)))
    tickets.created_ids.extend(ids)
    return ids


class _Sampler(threading.Thread):
    """后台每 interval 秒采一次 (队列深度, 指标快照),用例结束后拿峰值和速率"""

    def __init__(self, rabbit, metrics, interval: float = 0.5):
        super().__init__(daemon=True)
        self.rabbit, self.metrics, self.interval = rabbit, metrics, interval
        self.samples: list[tuple[float, int, float, float]] = []    # (t, depth, consumed_total, pending)
        self._halt = threading.Event()   # 不能叫 _stop:threading.Thread 自己有 _stop 方法

    def run(self):
        while not self._halt.is_set():
            snap = self.metrics.snapshot()
            depth = self.rabbit.queue_depth("STATUS_CHANGED")
            self.samples.append((time.monotonic(), depth,
                                 self.metrics._match(snap, "mq_event_consumed_total", {}),
                                 self.metrics._match(snap, "hikaricp_connections_pending", {})))
            self._halt.wait(self.interval)

    def stop(self):
        self._halt.set()
        self.join(timeout=5)

    def max_depth(self) -> int:
        return max((d for _, d, _, _ in self.samples), default=0)

    def max_pending(self) -> float:
        return max((p for _, _, _, p in self.samples), default=0)

    def consume_rate_between(self, t0: float, t1: float) -> float:
        window = [(t, c) for t, _, c, _ in self.samples if t0 <= t <= t1]
        if len(window) < 2 or window[-1][0] == window[0][0]:
            return float("nan")
        return (window[-1][1] - window[0][1]) / (window[-1][0] - window[0][0])


@allure.story("MQ 生产 > 消费")
class TestMqBacklog:

    @allure.title("20 线程创建 6 秒(生产 > 消费):队列深度上升、停止后 60 秒内清空、published == consumed、去重表一条不少")
    def test_backlog_drains_without_loss(self, tickets, config, rabbit, metrics, metrics_before):
        wait_until(lambda: rabbit.queue_depth("STATUS_CHANGED"), lambda d: d == 0, timeout=60, interval=1, what="队列起点为空")
        sampler = _Sampler(rabbit, metrics)
        sampler.start()
        t0 = time.monotonic()
        responses = blast(config.base_url, Users.ADMIN, threads=20, seconds=6,
                          fn=lambda c, i: c.create_ticket(f"capacity mq {i}", "x", group_id=1))
        t_load_end = time.monotonic()
        ids = _track_all(tickets, responses)
        produced = len(ids)
        assert produced > 0 and all(r.status == 201 for r in responses), "创建全部应 201"

        wait_until(lambda: (rabbit.queue_depth("STATUS_CHANGED"), metrics.delta(metrics_before, "mq_event_consumed_total")),
                   lambda v: v[0] == 0 and v[1] >= metrics.delta(metrics_before, "mq_event_published_total"),
                   timeout=60, interval=0.5, what="队列清空且 consumed == published")
        t_drained = time.monotonic()
        sampler.stop()

        published = metrics.delta(metrics_before, "mq_event_published_total")
        consumed = metrics.delta(metrics_before, "mq_event_consumed_total")
        failed = metrics.delta(metrics_before, "mq_event_publish_failed_total")
        rate_during = sampler.consume_rate_between(t0, t_load_end)
        rate_after = sampler.consume_rate_between(t_load_end, t_drained)
        allure.attach("\n".join([
            f"生产 {produced} 张 / {t_load_end - t0:.1f}s = {produced / (t_load_end - t0):.0f} 张/s(每张 1 条 STATUS_CHANGED)",
            f"published={published} consumed={consumed} publish_failed={failed}",
            f"队列深度峰值 {sampler.max_depth()}",
            f"消费速率:压测中 {rate_during:.0f} 条/s,压测停止后 {rate_after:.0f} 条/s",
            f"停止后清空用时 {t_drained - t_load_end:.1f}s",
        ]), name="MQ 容量观测", attachment_type=allure.attachment_type.TEXT)

        assert failed == 0
        assert consumed >= published, "一条不丢:消费数 >= 发布数(去重表是消费的证据)"
        assert t_drained - t_load_end <= 60
        # 去重表逐张核对:每张新单的 STATUS_CHANGED 都被消费过一次
        marks = ",".join(["%s"] * len(ids))
        rows = tickets.db.query(f"SELECT ticket_id, COUNT(*) AS n FROM mq_message_dedup WHERE ticket_id IN ({marks}) GROUP BY ticket_id", ids)
        assert len(rows) == produced and all(r["n"] == 1 for r in rows), f"去重表覆盖 {len(rows)}/{produced}"


@allure.story("SLA 到期高峰")
class TestSlaBacklog:

    @allure.title("250 张单同时到期:每轮扫描最多 batch(100)张,至少 ceil(250/100) 轮扫完,每张恰升级 1 次,记录吞吐")
    def test_burst_of_overdue_tickets(self, tickets, api, db, config, metrics, metrics_before):
        n_tickets = 250
        ids = create_many(tickets, config, n_tickets, threads=10, title="capacity sla")
        marks = ",".join(["%s"] * len(ids))
        # 截止时间拨到 10 天前:扫描按 sla_deadline 升序取,保证这 250 张排在库里任何历史积压(压测遗留)前面
        db.execute(f"UPDATE ticket SET sla_deadline = TIMESTAMPADD(DAY, -10, NOW(3)) WHERE id IN ({marks})", ids)
        foreign_backlog = db.scalar("SELECT COUNT(*) AS c FROM ticket WHERE status IN ('PENDING','ASSIGNED') AND escalated_at IS NULL "
                                    f"AND sla_deadline <= NOW(3) AND id NOT IN ({marks})", ids)

        batch = config.sla_scan_batch_size
        per_round, t0 = [], time.monotonic()
        for _ in range(12):
            per_round.append(api.sla_scan().expect.ok().resp.data["escalated"])
            remaining = db.scalar(f"SELECT COUNT(*) AS c FROM ticket WHERE id IN ({marks}) AND status <> 'ESCALATED'", ids)
            if remaining == 0:
                break
        elapsed = time.monotonic() - t0
        scans_total = metrics.delta(metrics_before, "sla_scan_total")      # 含后台调度器在此期间跑的轮次

        states = db.query(f"SELECT status FROM ticket WHERE id IN ({marks})", ids)
        escalations = db.query(f"SELECT ticket_id, COUNT(*) AS n FROM ticket_audit_log WHERE ticket_id IN ({marks}) AND to_status='ESCALATED' GROUP BY ticket_id", ids)
        allure.attach("\n".join([
            f"手动扫描每轮升级数 {per_round}(batch={batch});期间总扫描轮次(含后台)= {scans_total:.0f}",
            f"库里另有 {foreign_backlog} 张历史到期积压(它们排在本用例的 250 张之后)",
            f"{len(ids)} 张 / {elapsed:.1f}s;按调度器 30 s 一轮换算,{len(ids)} 张到期高峰需要 {math.ceil(len(ids) / batch) * 30}s 才能升级完(KI-013)",
        ]), name="SLA 积压观测", attachment_type=allure.attachment_type.TEXT)

        assert all(n <= batch for n in per_round), "单轮不超过 scan-batch-size"
        assert scans_total >= math.ceil(len(ids) / batch), "至少要 ceil(N/batch) 轮"
        assert all(s["status"] == "ESCALATED" for s in states), f"{sum(1 for s in states if s['status'] != 'ESCALATED')} 张没升级完"
        assert len(escalations) == len(ids) and all(e["n"] == 1 for e in escalations), "每张恰升级一次(防重复触发)"


@allure.story("连接池被 HTTP 打满时的消费者")
class TestConsumerStarvation:

    @allure.title("40 线程创建 8 秒把 HikariCP 打满(pending>0):期间消费速率不归零,停止后 60 秒内积压清完")
    def test_consumer_not_starved_when_pool_saturated(self, tickets, config, rabbit, metrics, metrics_before, warmed_pool):
        """前提"池被打满"由环境构造,不由用例猜(ADR-023):服务用小池起(HIKARI_MAX_POOL_SIZE=3,CI 单独一步),
        40 线程的负载源在任何机器上都能排起队。前提不成立仍然是失败而不是 skip,消息里带池大小 / pending 峰值 / req/s。"""
        pool_max = int(warmed_pool[1])
        wait_until(lambda: rabbit.queue_depth("STATUS_CHANGED"), lambda d: d == 0, timeout=60, interval=1, what="队列起点为空")
        sampler = _Sampler(rabbit, metrics, interval=0.5)
        sampler.start()
        t0 = time.monotonic()
        responses = blast(config.base_url, Users.ADMIN, threads=40, seconds=8,
                          fn=lambda c, i: c.create_ticket(f"capacity starve {i}", "x", group_id=1))
        t_load_end = time.monotonic()
        ids = _track_all(tickets, responses)

        wait_until(lambda: rabbit.queue_depth("STATUS_CHANGED"), lambda d: d == 0, timeout=60, interval=0.5, what="积压清空")
        t_drained = time.monotonic()
        sampler.stop()

        rate_during = sampler.consume_rate_between(t0 + 1, t_load_end)     # 去掉起步第 1 秒
        rate_after = sampler.consume_rate_between(t_load_end, t_drained)
        req_per_s = len(ids) / max(t_load_end - t0, 0.001)
        allure.attach("\n".join([
            f"HikariCP max={pool_max};生产 {len(ids)} 张 / {t_load_end - t0:.1f}s = {req_per_s:.0f} req/s;pending 峰值 {sampler.max_pending():.0f}(>0 即池被打满)",
            f"队列深度峰值 {sampler.max_depth()}",
            f"消费速率:池满期间 {rate_during:.0f} 条/s,停止后 {rate_after:.0f} 条/s(压测记录:190 → ~110)",
            f"停止后清空用时 {t_drained - t_load_end:.1f}s",
        ]), name="消费者饥饿观测", attachment_type=allure.attachment_type.TEXT)

        assert sampler.max_pending() > 0, (
            f"前提不成立:池没有被打满,这条用例没测到想测的场景——HikariCP max={pool_max},"
            f"40 线程打出 {req_per_s:.0f} req/s({len(ids)} 张 / {t_load_end - t0:.1f}s),pending 峰值 {sampler.max_pending():.0f}。"
            f"服务应以 HIKARI_MAX_POOL_SIZE=3 起(ADR-023);仍打不满说明负载源比这台机器的服务端慢太多")
        assert rate_during > 0, "池满期间消费者被饿死(消费速率为 0)"
        assert metrics.delta(metrics_before, "mq_event_consumed_total") >= metrics.delta(metrics_before, "mq_event_published_total")
