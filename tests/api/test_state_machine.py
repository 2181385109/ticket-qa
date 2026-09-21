"""
状态机——状态迁移法(docs/test-design/01)。

SPEC 是规格(CLAUDE.md §5.1)的独立抄本。36 格 = 11 合法 + 25 非法,非法格逐格打,不挑。
每一格先用工厂把工单造到 from 状态(走真实接口链),再打 to,断言 409/40901 且状态不变、审计不增。
合法路径用例从表推导:一条主干路径 + 每条边至少被一条用例覆盖。
"""
import allure
import pytest

from framework.factory import STATUSES
from framework.users import Users

pytestmark = [allure.feature("状态机")]

SPEC = {
    "PENDING": {"ASSIGNED", "ESCALATED"},
    "ASSIGNED": {"PROCESSING", "PENDING", "ESCALATED"},
    "PROCESSING": {"WAIT_CONFIRM", "ESCALATED"},
    "WAIT_CONFIRM": {"CLOSED", "PROCESSING"},
    "CLOSED": {"PROCESSING"},
    "ESCALATED": {"ASSIGNED"},
}
ILLEGAL_CELLS = [(f, t) for f in STATUSES for t in STATUSES if t not in SPEC[f]]
assert len(ILLEGAL_CELLS) == 25 and sum(len(v) for v in SPEC.values()) == 11


def _actor_and_body(target: str) -> tuple:
    """流转到 ASSIGNED 需要 LEADER + assigneeId;其余用 ADMIN(写权限全覆盖,排除权限因素)"""
    if target == "ASSIGNED":
        return Users.LEADER_1, dict(assignee_id=Users.AGENT_B.id)
    return Users.ADMIN, {}


@allure.story("非法流转:25 格逐格")
class TestIllegalTransitions:

    @pytest.mark.parametrize("src, dst", ILLEGAL_CELLS, ids=[f"{f}->{t}" for f, t in ILLEGAL_CELLS])
    @allure.title("{src} → {dst} 非法:409 / 40901,状态不变,不新增审计")
    def test_illegal_cell(self, tickets, api, db, src, dst):
        t = tickets.in_status(src)
        audits_before = len(db.audit_logs(t["id"]))
        actor, body = _actor_and_body(dst)

        resp = api.as_user(actor).transit(t["id"], dst, **body)

        resp.expect.error(409, 40901).body("message").contains(src).body("message").contains(dst)
        api.get_ticket(t["id"]).expect.ok().data("status").eq(src)
        assert len(db.audit_logs(t["id"])) == audits_before, "非法流转不能落审计"


@allure.story("合法流转:主干路径与每条边")
class TestLegalPaths:

    @allure.title("主干:PENDING→ASSIGNED(抢单)→PROCESSING→WAIT_CONFIRM→CLOSED→PROCESSING(重开),审计逐条对应")
    def test_main_path_with_audit(self, tickets, api):
        agent = api.as_user(Users.AGENT_A)
        t = tickets.create(group_id=1)
        tid = t["id"]
        agent.grab(tid).expect.ok().data("status").eq("ASSIGNED").data("assigneeId").eq(Users.AGENT_A.id)
        agent.transit(tid, "PROCESSING", remark="开始处理").expect.ok().data("status").eq("PROCESSING")
        agent.transit(tid, "WAIT_CONFIRM").expect.ok().data("status").eq("WAIT_CONFIRM")
        closed = agent.transit(tid, "CLOSED")
        closed.expect.ok().data("status").eq("CLOSED").data("closedAt").not_none()
        reopened = agent.transit(tid, "PROCESSING", remark="7 天内重开")
        reopened.expect.ok().data("status").eq("PROCESSING")
        reopened.expect.lacks_keys("closedAt")

        logs = api.audit_logs(tid).expect.ok().resp.data
        pairs = [(l.get("fromStatus"), l["toStatus"], l["source"]) for l in logs]
        assert pairs == [
            (None, "PENDING", "LLM"),
            ("PENDING", "ASSIGNED", "MANUAL"),
            ("ASSIGNED", "PROCESSING", "MANUAL"),
            ("PROCESSING", "WAIT_CONFIRM", "MANUAL"),
            ("WAIT_CONFIRM", "CLOSED", "MANUAL"),
            ("CLOSED", "PROCESSING", "MANUAL"),
        ], pairs
        assert all(l["traceId"] for l in logs)
        assert logs[2]["remark"] == "开始处理"

    @allure.title("ASSIGNED → PENDING 退回:assignee 清空,组内其他坐席可再抢")
    def test_return_to_pending_clears_assignee(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        back = api.as_user(Users.AGENT_A).transit(t["id"], "PENDING", remark="退回")
        back.expect.ok().data("status").eq("PENDING").lacks_keys("assigneeId")
        api.as_user(Users.AGENT_B).grab(t["id"]).expect.ok().data("assigneeId").eq(Users.AGENT_B.id)

    @allure.title("WAIT_CONFIRM → PROCESSING 用户不认可:回到处理中,closedAt 仍为空")
    def test_customer_rejects(self, tickets, api):
        t = tickets.wait_confirm(Users.AGENT_A)
        api.as_user(Users.AGENT_A).transit(t["id"], "PROCESSING", remark="用户不认可") \
            .expect.ok().data("status").eq("PROCESSING").lacks_keys("closedAt")

    @pytest.mark.parametrize("src", ["PENDING", "ASSIGNED", "PROCESSING"])
    @allure.title("{src} → ESCALATED 人工升级(ADMIN)")
    def test_manual_escalate(self, tickets, api, src):
        t = tickets.in_status(src)
        api.transit(t["id"], "ESCALATED", remark="人工升级").expect.ok().data("status").eq("ESCALATED")

    @allure.title("ESCALATED → ASSIGNED 只能由组长 / ADMIN 指派,不能抢")
    def test_escalated_back_to_assigned(self, tickets, api):
        t = tickets.escalated(group_id=1)
        api.as_user(Users.AGENT_A).grab(t["id"]).expect.error(409, 40901)
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_A.id).expect.ok().data("status").eq("ASSIGNED")


@allure.story("重开窗口:7 天闭区间")
@pytest.mark.db
class TestReopenWindow:

    @allure.title("关闭 6.9 天:可重开")
    def test_reopen_inside_window(self, tickets, api, db):
        t = tickets.closed(Users.AGENT_A)
        db.set_closed_at_days_ago(t["id"], 6.9)
        api.as_user(Users.AGENT_A).transit(t["id"], "PROCESSING").expect.ok().data("status").eq("PROCESSING")

    @allure.title("关闭 7 天零 1 分钟:拒绝重开 409,message 说明超窗")
    def test_reopen_outside_window(self, tickets, api, db):
        t = tickets.closed(Users.AGENT_A)
        db.set_closed_at_days_ago(t["id"], 7 + 1 / 1440)
        (api.as_user(Users.AGENT_A).transit(t["id"], "PROCESSING")
         .expect.error(409, 40901).body("message").contains("7 天"))
        api.get_ticket(t["id"]).expect.ok().data("status").eq("CLOSED")

    @allure.title("已关闭的工单不能改标题内容 → 409 / 40902")
    def test_closed_ticket_is_immutable(self, tickets, api):
        t = tickets.closed(Users.AGENT_A)
        api.update_ticket(t["id"], "x", "y").expect.error(409, 40902)
