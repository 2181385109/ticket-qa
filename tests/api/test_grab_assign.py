"""
抢单与指派 / 改派——判定表法(docs/test-design/04):角色 × 组 × 工单状态 → 结果。
"""
import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("工单")]


@allure.story("抢单")
class TestGrab:

    @allure.title("本组坐席抢 PENDING 单:ASSIGNED、assignee=自己、审计备注「抢单」")
    def test_grab_pending(self, tickets, api, db):
        t = tickets.pending(group_id=1)
        resp = api.as_user(Users.AGENT_A).grab(t["id"])
        resp.expect.ok().data("status").eq("ASSIGNED").data("assigneeId").eq(Users.AGENT_A.id)
        last = db.audit_logs(t["id"])[-1]
        assert (last["from_status"], last["to_status"], last["operator_id"], last["remark"]) == ("PENDING", "ASSIGNED", 3, "抢单")

    @allure.title("已被抢的单再抢 → 409 / 40901,assignee 不变")
    def test_grab_twice(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_B).grab(t["id"]).expect.error(409, 40901)
        api.get_ticket(t["id"]).expect.ok().data("assigneeId").eq(Users.AGENT_A.id)

    @pytest.mark.parametrize("user", [Users.AGENT_C, Users.LEADER_2], ids=lambda u: u.username)
    @allure.title("跨组 {user} 抢 1 组的单 → 403 / 40301")
    def test_grab_across_group(self, tickets, api, user):
        t = tickets.pending(group_id=1)
        api.as_user(user).grab(t["id"]).expect.error(403, 40301)

    @allure.title("组长和 ADMIN 也能抢(抢单只看组,不看角色)")
    def test_leader_and_admin_can_grab(self, tickets, api):
        t1 = tickets.pending(group_id=1)
        api.as_user(Users.LEADER_1).grab(t1["id"]).expect.ok().data("assigneeId").eq(Users.LEADER_1.id)
        t2 = tickets.pending(group_id=2)
        api.grab(t2["id"]).expect.ok().data("assigneeId").eq(Users.ADMIN.id)

    @allure.title("抢不存在的工单 → 404 / 40401")
    def test_grab_missing(self, api):
        api.as_user(Users.AGENT_A).grab(99999999).expect.error(404, 40401)


@allure.story("指派 / 改派")
class TestAssign:

    @allure.title("组长指派 PENDING 单:ASSIGNED,审计备注含「指派给」")
    def test_leader_assigns_pending(self, tickets, api, db):
        t = tickets.pending(group_id=1)
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_B.id, remark="你来").expect.ok() \
            .data("status").eq("ASSIGNED").data("assigneeId").eq(Users.AGENT_B.id)
        assert "指派给 4" in db.audit_logs(t["id"])[-1]["remark"]

    @allure.title("组长改派 ASSIGNED 单:只换人不换状态,审计 from=to=ASSIGNED,备注含「改派 3 -> 4」")
    def test_leader_reassigns(self, tickets, api, db):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_B.id).expect.ok() \
            .data("status").eq("ASSIGNED").data("assigneeId").eq(Users.AGENT_B.id)
        last = db.audit_logs(t["id"])[-1]
        assert (last["from_status"], last["to_status"]) == ("ASSIGNED", "ASSIGNED")
        assert "改派 3 -> 4" in last["remark"]
        # 原坐席失去访问权,新坐席获得
        api.as_user(Users.AGENT_A).get_ticket(t["id"]).expect.error(403, 40301)
        api.as_user(Users.AGENT_B).get_ticket(t["id"]).expect.ok()

    @allure.title("指派给别组坐席 → 400 / 40003")
    def test_assign_to_other_group_agent(self, tickets, api):
        t = tickets.pending(group_id=1)
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_C.id).expect.error(400, 40003)

    @allure.title("指派给不存在的坐席 → 404 / 40402")
    def test_assign_to_unknown_agent(self, tickets, api):
        t = tickets.pending(group_id=1)
        api.as_user(Users.LEADER_1).assign(t["id"], 999).expect.error(404, 40402)

    @pytest.mark.parametrize("body", [{}, {"assigneeId": None}, {"assigneeId": 0}, {"assigneeId": -3}, {"assigneeId": "abc"}],
                             ids=["missing", "null", "zero", "negative", "string"])
    @allure.title("assigneeId 无效 {body} → 400 / 40001")
    def test_assign_invalid_body(self, tickets, api, body):
        t = tickets.pending(group_id=1)
        api.as_user(Users.LEADER_1).post(f"/api/tickets/{t['id']}/assign", body).expect.error(400, 40001)

    @allure.title("transitions 接口流转到 ASSIGNED 但不带 assigneeId → 400 / 40002")
    def test_transition_to_assigned_requires_assignee(self, tickets, api):
        t = tickets.pending(group_id=1)
        api.as_user(Users.LEADER_1).transit(t["id"], "ASSIGNED").expect.error(400, 40002)

    @allure.title("ADMIN 可跨组指派")
    def test_admin_assigns_any_group(self, tickets, api):
        t = tickets.pending(group_id=2)
        api.assign(t["id"], Users.AGENT_C.id).expect.ok().data("assigneeId").eq(Users.AGENT_C.id)

    @allure.title("PROCESSING 的单不能改派 → 409(PROCESSING → ASSIGNED 不在迁移表)")
    def test_cannot_reassign_processing(self, tickets, api):
        t = tickets.processing(Users.AGENT_A)
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_B.id).expect.error(409, 40901)


@allure.story("列表按角色收窄")
class TestList:

    @pytest.fixture(scope="class")
    def seeded(self, module_factory):
        """两组各两张:1 组一张给 agent_a、一张 PENDING;2 组一张给 agent_c、一张 PENDING"""
        return {
            "a": module_factory.assigned(Users.AGENT_A),
            "p1": module_factory.pending(group_id=1),
            "c": module_factory.assigned(Users.AGENT_C),
            "p2": module_factory.pending(group_id=2),
        }

    @allure.title("AGENT 只看到分配给自己的")
    def test_agent_sees_own_only(self, api, seeded):
        resp = api.as_user(Users.AGENT_A).list_tickets(page=1, size=200)
        resp.expect.ok().data("records").each(lambda r: r.get("assigneeId") == Users.AGENT_A.id, "assigneeId == agent_a")
        ids = {r["id"] for r in resp.data["records"]}
        assert seeded["a"]["id"] in ids and seeded["p1"]["id"] not in ids and seeded["c"]["id"] not in ids

    @allure.title("LEADER 看到本组全部(含 PENDING),看不到别组")
    def test_leader_sees_group(self, api, seeded):
        resp = api.as_user(Users.LEADER_2).list_tickets(page=1, size=200)
        resp.expect.ok().data("records").each(lambda r: r["groupId"] == 2, "groupId == 2")
        ids = {r["id"] for r in resp.data["records"]}
        assert {seeded["c"]["id"], seeded["p2"]["id"]} <= ids and seeded["a"]["id"] not in ids

    @allure.title("ADMIN 看到全部,status 过滤生效")
    def test_admin_sees_all_with_filter(self, api, seeded):
        resp = api.list_tickets(status="PENDING", page=1, size=200)
        resp.expect.ok().data("records").each(lambda r: r["status"] == "PENDING", "status == PENDING")
        ids = {r["id"] for r in resp.data["records"]}
        assert {seeded["p1"]["id"], seeded["p2"]["id"]} <= ids and seeded["a"]["id"] not in ids

    @allure.title("分页字段:total / page / size,records 不超过 size")
    def test_pagination_shape(self, api, seeded):
        resp = api.list_tickets(page=1, size=2)
        (resp.expect.ok().has_keys("records", "total", "page", "size")
         .data("page").eq(1).data("size").eq(2)
         .data("records").satisfies(lambda r: len(r) <= 2, "len <= size")
         .data("total").ge(4))

    @pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 201}, {"page": -1}, {"status": "FOO"}, {"page": "x"}],
                             ids=["page0", "size0", "size201", "page-1", "bad-status", "page-str"])
    @allure.title("分页参数越界 {params} → 400 / 40001")
    def test_invalid_paging(self, api, params):
        api.list_tickets(**params).expect.error(400, 40001)
