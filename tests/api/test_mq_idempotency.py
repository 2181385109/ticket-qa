"""
MQ 异步链路与消费幂等(ADR-003)——场景法。

S1 状态变更 → 三类事件各进各的队列、各自消费者在去重表留一行
S2 同一 messageId 再投一次 → 去重表不增、业务不重跑、mq_event_duplicate_total +1
S3 内容相同但 messageId 不同 → 当作新消息处理(去重靠 id,不靠内容)
"""
import uuid

import allure
import pytest

from framework.users import Users
from framework.waits import wait_until

pytestmark = [allure.feature("MQ"), pytest.mark.mq, pytest.mark.db]


def _wait_rows(db, ticket_id, expect_types: set[str], timeout: float = 10):
    return wait_until(lambda: db.dedup_rows(ticket_id),
                      lambda rs: expect_types <= {r["event_type"] for r in rs},
                      timeout=timeout, what=f"工单 {ticket_id} 的 {expect_types} 消息被消费")


@allure.story("事件投递与消费")
class TestDelivery:

    @allure.title("抢单发 STATUS_CHANGED + ASSIGNED 两条事件,messageId 不同,各由对应消费者消费一次")
    def test_grab_publishes_two_events(self, tickets, api, db, metrics, metrics_before):
        t = tickets.pending(group_id=1)
        api.as_user(Users.AGENT_A).grab(t["id"]).expect.ok()
        rows = _wait_rows(db, t["id"], {"ASSIGNED"})
        assigned = [r for r in rows if r["event_type"] == "ASSIGNED"]
        changed = [r for r in rows if r["event_type"] == "STATUS_CHANGED"]
        assert len(assigned) == 1 and assigned[0]["consumer"] == "assigned-notifier"
        assert len(changed) == 2, "创建 + 抢单 各一条 STATUS_CHANGED"
        assert all(r["consumer"] == "status-changed-notifier" for r in changed)
        assert len({r["message_id"] for r in rows}) == len(rows), "每条消息 id 唯一"
        assert metrics.delta(metrics_before, "mq_event_published_total") >= 3
        assert metrics.delta(metrics_before, "mq_event_consumed_total") >= 3

    @allure.title("消费记录带 traceId,与触发它的 HTTP 请求的 X-Trace-Id 一致(跨线程传递)")
    def test_trace_id_propagates_to_consumer(self, tickets, api, db):
        t = tickets.pending(group_id=1)
        trace = "qa-mq-" + uuid.uuid4().hex[:8]
        api.request("POST", f"/api/tickets/{t['id']}/grab", headers={"X-Trace-Id": trace}, user=Users.AGENT_A).expect.ok()
        rows = _wait_rows(db, t["id"], {"ASSIGNED"})
        assert any(r["trace_id"] == trace for r in rows if r["event_type"] == "ASSIGNED")

    @allure.title("非法流转不发事件:409 之后去重表没有新增")
    def test_illegal_transition_publishes_nothing(self, tickets, api, db):
        t = tickets.assigned(Users.AGENT_A)
        before = _wait_rows(db, t["id"], {"ASSIGNED"})
        api.as_user(Users.AGENT_A).transit(t["id"], "CLOSED").expect.error(409, 40901)
        import time
        time.sleep(1.5)
        assert len(db.dedup_rows(t["id"])) == len(before)


@allure.story("消费幂等:去重表")
class TestIdempotency:

    @allure.title("同一 messageId 重投:去重表不增,mq_event_duplicate_total +1,consumed 不增")
    def test_redelivery_is_deduplicated(self, tickets, api, db, rabbit, metrics, metrics_before):
        t = tickets.pending(group_id=1)
        api.as_user(Users.AGENT_A).grab(t["id"]).expect.ok()
        rows = _wait_rows(db, t["id"], {"ASSIGNED"})
        target = next(r for r in rows if r["event_type"] == "ASSIGNED")
        count_before = len(rows)
        consumed_before = metrics.value("mq_event_consumed_total")

        payload = rabbit.message_from_dedup_row(target, t, "PENDING", "ASSIGNED")
        assert rabbit.publish("ASSIGNED", payload), "管理 API 应能把消息路由到队列"

        wait_until(lambda: metrics.delta(metrics_before, "mq_event_duplicate_total"), lambda d: d >= 1,
                   timeout=10, what="重复消息被识别")
        assert len(db.dedup_rows(t["id"])) == count_before
        assert metrics.value("mq_event_consumed_total") == consumed_before

    @allure.title("内容相同、messageId 不同:视为新消息,去重表 +1(幂等键是 id 不是内容)")
    def test_new_message_id_is_processed(self, tickets, api, db, rabbit):
        t = tickets.pending(group_id=1)
        api.as_user(Users.AGENT_A).grab(t["id"]).expect.ok()
        rows = _wait_rows(db, t["id"], {"ASSIGNED"})
        target = dict(next(r for r in rows if r["event_type"] == "ASSIGNED"))
        target["message_id"] = str(uuid.uuid4())

        rabbit.publish("ASSIGNED", rabbit.message_from_dedup_row(target, t, "PENDING", "ASSIGNED"))

        wait_until(lambda: db.dedup_rows(t["id"]), lambda rs: len(rs) == len(rows) + 1, timeout=10,
                   what="新 messageId 被消费")
        assert any(r["message_id"] == target["message_id"] and r["consumer"] == "assigned-notifier" for r in db.dedup_rows(t["id"]))

    @allure.title("同一 messageId 投到不同队列:两个消费者各处理一次(唯一键含 consumer)")
    def test_same_id_different_consumers(self, tickets, api, db, rabbit):
        t = tickets.pending(group_id=1)
        api.as_user(Users.AGENT_A).grab(t["id"]).expect.ok()
        rows = _wait_rows(db, t["id"], {"ASSIGNED"})
        target = dict(next(r for r in rows if r["event_type"] == "ASSIGNED"))
        # 用 ASSIGNED 的 messageId 发一条 STATUS_CHANGED 路由键的消息 → status-changed-notifier 视为首次
        payload = rabbit.message_from_dedup_row(target, t, "PENDING", "ASSIGNED")
        payload["eventType"] = "STATUS_CHANGED"
        rabbit.publish("STATUS_CHANGED", payload)

        wait_until(lambda: db.dedup_rows(t["id"]), lambda rs: len(rs) == len(rows) + 1, timeout=10,
                   what="另一消费者处理同 id 消息")
        consumers = {r["consumer"] for r in db.dedup_rows(t["id"]) if r["message_id"] == target["message_id"]}
        assert consumers == {"assigned-notifier", "status-changed-notifier"}

    @allure.title("队列消费后无积压(每条消息都被 ack)")
    def test_queues_drain(self, tickets, api, rabbit, db):
        t = tickets.pending(group_id=1)
        api.as_user(Users.AGENT_A).grab(t["id"]).expect.ok()
        _wait_rows(db, t["id"], {"ASSIGNED"})
        for q in ("STATUS_CHANGED", "ASSIGNED", "SLA_ESCALATED"):
            wait_until(lambda q=q: rabbit.queue_depth(q), lambda d: d == 0, timeout=10, what=f"队列 {q} 清空")
