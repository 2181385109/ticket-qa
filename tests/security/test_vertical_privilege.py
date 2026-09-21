"""
垂直越权:角色不够——AGENT 调 LEADER / ADMIN 的接口(CLAUDE.md §5.6)。
期望 403 / 40302(区别于水平越权的 40301)。

判定表:接口 × 角色(AGENT / LEADER / ADMIN)。
"""
import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("安全"), allure.story("垂直越权")]


class TestAssignIsLeaderOnly:

    @allure.title("AGENT 调改派接口(哪怕是自己的单、改给自己)→ 403 / 40302")
    def test_agent_cannot_assign_even_own_ticket(self, api, tickets):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_A).assign(t["id"], Users.AGENT_A.id).expect.error(403, 40302)
        api.as_user(Users.AGENT_A).assign(t["id"], Users.AGENT_B.id).expect.error(403, 40302)

    @allure.title("AGENT 绕开 assign 接口、用 transitions 把目标状态写成 ASSIGNED → 仍然 40302(校验在 Service 层)")
    def test_agent_cannot_assign_via_transitions(self, api, tickets, db):
        # 从 ASSIGNED 升级成 ESCALATED 的单仍挂着 assignee=agent_a:写权限够,ESCALATED→ASSIGNED 也是合法边,
        # 唯一拦住它的只能是角色检查
        t = tickets.assigned(Users.AGENT_A)
        db.set_sla_deadline_now(t["id"], offset_seconds=-1)
        api.sla_scan().expect.ok()
        api.get_ticket(t["id"]).expect.ok().data("status").eq("ESCALATED").data("assigneeId").eq(Users.AGENT_A.id)
        api.as_user(Users.AGENT_A).transit(t["id"], "ASSIGNED", assignee_id=Users.AGENT_A.id).expect.error(403, 40302)
        api.get_ticket(t["id"]).expect.ok().data("status").eq("ESCALATED")

    @allure.title("AGENT 对 PENDING 单同时缺写权限和角色:先报水平(40301)——权限检查顺序 checkWrite → checkAssign")
    def test_check_order_on_pending(self, api, tickets):
        t = tickets.pending(group_id=1)
        api.as_user(Users.AGENT_A).transit(t["id"], "ASSIGNED", assignee_id=Users.AGENT_A.id).expect.error(403, 40301)

    @allure.title("LEADER 只能改派本组;跨组是水平越权 40301 而不是 40302")
    def test_leader_scope(self, api, tickets):
        t = tickets.assigned(Users.AGENT_C)      # 2 组
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_C.id).expect.error(403, 40301)
        api.as_user(Users.LEADER_2).assign(t["id"], Users.AGENT_C.id).expect.ok()


class TestAdminOnly:

    @pytest.mark.parametrize("user", [Users.AGENT_A, Users.LEADER_1, Users.LEADER_2], ids=lambda u: u.username)
    @allure.title("{user} 删除工单 → 403 / 40302,工单仍在")
    def test_delete_requires_admin(self, api, tickets, user):
        t = tickets.pending(group_id=user.group_id)
        api.as_user(user).delete_ticket(t["id"]).expect.error(403, 40302)
        api.get_ticket(t["id"]).expect.ok()

    @pytest.mark.parametrize("user", [Users.AGENT_A, Users.LEADER_1], ids=lambda u: u.username)
    @allure.title("{user} 触发 SLA 扫描 → 403 / 40302")
    def test_sla_scan_requires_admin(self, api, user):
        api.as_user(user).sla_scan().expect.error(403, 40302)

    @allure.title("对照:ADMIN 删除 / 扫描 / 跨组改派 全部放行")
    def test_admin_allowed(self, api, tickets):
        t = tickets.pending(group_id=2)
        api.assign(t["id"], Users.AGENT_C.id).expect.ok()
        api.sla_scan().expect.ok()
        api.delete_ticket(t["id"]).expect.ok()


class TestRoleForgery:

    @allure.title("角色不能通过请求体 / 查询参数 / 额外头伪造:带 role=ADMIN 的 AGENT 仍是 AGENT")
    def test_role_cannot_be_injected(self, api, tickets):
        t = tickets.pending(group_id=1)
        agent = api.as_user(Users.AGENT_A)
        agent.request("DELETE", f"/api/tickets/{t['id']}", params={"role": "ADMIN"}).expect.error(403, 40302)
        agent.request("DELETE", f"/api/tickets/{t['id']}", headers={"X-Role": "ADMIN", "X-User-Role": "ADMIN"}).expect.error(403, 40302)
        agent.post(f"/api/tickets/{t['id']}/assign", {"assigneeId": 3, "role": "ADMIN", "operator": {"role": "ADMIN"}}).expect.error(403, 40302)
        agent.me().expect.ok().data("role").eq("AGENT")

    @allure.title("X-User-Id 给逗号分隔的多个值 / 带控制字符 → 401,不会被解析成其中某一个用户")
    def test_user_id_header_tricks(self, api):
        api.request("GET", "/api/agents/me", headers={"X-User-Id": "3, 1"}, user=None).expect.error(401, 40101)
        api.request("GET", "/api/agents/me", headers={"X-User-Id": "3	1"}, user=None).expect.error(401, 40101)
