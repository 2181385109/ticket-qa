"""
SLA 自动升级——边界值分析 + 场景法(docs/test-design/02)。

接口层面能控制的变量只有 sla_deadline(直接改库)和"什么时候扫"。"恰好等于"这个点在接口层面
碰不到(扫描的 now 是服务取的),所以这里取 deadline = now-1s(必超时)和 now+3s(必未超时,3.5 秒后再扫变超时)
两个点夹住边界;精确到毫秒的 <= vs < 由单测 SlaOverdueQueryH2Test 在真实 SQL 上证明。
"""
import time

import allure
import pytest

from framework.users import Users
from framework.waits import wait_until

pytestmark = [allure.feature("SLA"), pytest.mark.db]


@allure.story("自动升级")
class TestEscalation:

    @allure.title("截止时间已过的 PENDING 单:扫描后 ESCALATED、escalatedAt 有值、审计 source=SCHEDULER、指标 +1")
    def test_overdue_pending_is_escalated(self, tickets, api, db, metrics, metrics_before):
        t = tickets.pending(group_id=1)
        db.set_sla_deadline_now(t["id"], offset_seconds=-1)

        api.sla_scan().expect.ok().data("escalated").ge(1)

        after = api.get_ticket(t["id"])
        after.expect.ok().data("status").eq("ESCALATED").data("escalatedAt").not_none()
        sched = [l for l in db.audit_logs(t["id"]) if l["source"] == "SCHEDULER"]
        assert len(sched) == 1 and sched[0]["from_status"] == "PENDING" and sched[0]["to_status"] == "ESCALATED"
        assert sched[0]["operator_id"] is None and sched[0]["operator_name"] == "SCHEDULER"
        assert "deadline=" in sched[0]["remark"]
        assert metrics.delta(metrics_before, "sla_escalated_total") >= 1

    @allure.title("ASSIGNED 但未进入 PROCESSING 的超时单同样升级,assignee 保留")
    def test_overdue_assigned_is_escalated(self, tickets, api, db):
        t = tickets.assigned(Users.AGENT_A)
        db.set_sla_deadline_now(t["id"], offset_seconds=-1)
        api.sla_scan().expect.ok()
        api.get_ticket(t["id"]).expect.ok().data("status").eq("ESCALATED").data("assigneeId").eq(Users.AGENT_A.id)

    @pytest.mark.parametrize("status", ["PROCESSING", "WAIT_CONFIRM", "CLOSED"])
    @allure.title("已响应({status})的超时单不升级")
    def test_responded_ticket_not_escalated(self, tickets, api, db, status):
        t = tickets.in_status(status)
        db.set_sla_deadline_now(t["id"], offset_seconds=-60)
        api.sla_scan().expect.ok()
        api.get_ticket(t["id"]).expect.ok().data("status").eq(status).lacks_keys("escalatedAt")

    @allure.title("边界:deadline = now+3s 扫描不命中;3.5 秒后再扫命中(超时判定随时间单调)")
    @pytest.mark.slow
    def test_deadline_in_near_future(self, tickets, api, db):
        t = tickets.pending(group_id=1)
        db.set_sla_deadline_now(t["id"], offset_seconds=3)
        api.sla_scan().expect.ok()
        api.get_ticket(t["id"]).expect.ok().data("status").eq("PENDING")
        time.sleep(3.5)
        api.sla_scan().expect.ok()
        api.get_ticket(t["id"]).expect.ok().data("status").eq("ESCALATED")

    @allure.title("扫描接口只有 ADMIN 能调:LEADER / AGENT → 403 / 40302,匿名 → 401")
    def test_scan_permission(self, api, anon):
        api.as_user(Users.LEADER_1).sla_scan().expect.error(403, 40302)
        api.as_user(Users.AGENT_A).sla_scan().expect.error(403, 40302)
        anon.sla_scan().expect.error(401, 40101)


@allure.story("防重复触发")
class TestNoDoubleEscalation:

    @allure.title("同一工单连续扫两轮:第二轮升级数为 0,SCHEDULER 审计只有一条,skipped 指标不增(第二轮根本扫不到它)")
    def test_second_scan_is_noop(self, tickets, api, db, metrics, metrics_before):
        t = tickets.pending(group_id=1)
        db.set_sla_deadline_now(t["id"], offset_seconds=-1)
        api.sla_scan().expect.ok().data("escalated").ge(1)
        api.sla_scan().expect.ok().data("escalated").eq(0)
        assert sum(1 for l in db.audit_logs(t["id"]) if l["source"] == "SCHEDULER") == 1
        assert metrics.delta(metrics_before, "sla_escalated_total") == 1

    @allure.title("升级后被组长指派回 ASSIGNED、截止时间仍在过去:再扫不会二次升级(escalated_at 永久标记)")
    def test_reassigned_after_escalation_not_escalated_again(self, tickets, api, db):
        t = tickets.escalated(group_id=1)
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_A.id).expect.ok().data("status").eq("ASSIGNED")
        api.sla_scan().expect.ok()
        row = db.ticket(t["id"])
        assert row["status"] == "ASSIGNED" and row["escalated_at"] is not None
        assert sum(1 for l in db.audit_logs(t["id"]) if l["source"] == "SCHEDULER") == 1

    @allure.title("批量:三张超时单一轮全部升级,各自只有一条 SCHEDULER 审计")
    def test_batch_escalation(self, tickets, api, db):
        ids = [tickets.pending(group_id=g)["id"] for g in (1, 2, 1)]
        for i in ids:
            db.set_sla_deadline_now(i, offset_seconds=-1)
        api.sla_scan().expect.ok().data("escalated").ge(3)
        for i in ids:
            assert db.ticket(i)["status"] == "ESCALATED"
            assert sum(1 for l in db.audit_logs(i) if l["source"] == "SCHEDULER") == 1


@allure.story("升级事件进入 MQ")
@pytest.mark.mq
class TestEscalationEvents:

    @allure.title("升级后去重表出现 SLA_ESCALATED 与 STATUS_CHANGED 两类消费记录(消费者各一行)")
    def test_escalation_publishes_two_events(self, tickets, db):
        t = tickets.escalated(group_id=1)
        rows = wait_until(lambda: db.dedup_rows(t["id"]),
                          lambda rs: {"SLA_ESCALATED", "STATUS_CHANGED"} <= {r["event_type"] for r in rs},
                          timeout=10, what="SLA 升级的两条消息被消费")
        by_type = {r["event_type"]: r["consumer"] for r in rows}
        assert by_type["SLA_ESCALATED"] == "sla-escalated-notifier"
        assert by_type["STATUS_CHANGED"] == "status-changed-notifier"
