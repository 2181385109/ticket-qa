"""
查 / 改 / 删 + 审计轨迹一致性。
审计是"数据一致性校验"的载体(CLAUDE.md §5.8):每次状态变更恰好一条,字段与请求方一致。
"""
import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("工单")]


@allure.story("查询 / 修改 / 删除")
class TestCrud:

    @allure.title("详情:字段与创建时一致;不存在 → 404 / 40401")
    def test_get(self, tickets, api):
        t = tickets.create()
        api.get_ticket(t["id"]).expect.ok().data("ticketNo").eq(t["ticketNo"]).data("title").eq(t["title"])
        api.get_ticket(99999999).expect.error(404, 40401)

    @allure.title("修改标题 / 内容:返回新值,库里落地,不产生审计(不是状态变更)")
    def test_update(self, tickets, api, db):
        t = tickets.assigned(Users.AGENT_A)
        audits = len(db.audit_logs(t["id"]))
        api.as_user(Users.AGENT_A).update_ticket(t["id"], "新标题", "新内容").expect.ok() \
            .data("title").eq("新标题").data("content").eq("新内容").data("status").eq("ASSIGNED")
        assert db.ticket(t["id"])["title"] == "新标题"
        assert len(db.audit_logs(t["id"])) == audits

    @pytest.mark.parametrize("body", [{"title": "", "content": "x"}, {"title": "t"}, {"title": "标" * 201, "content": "x"}],
                             ids=["blank-title", "no-content", "title-201"])
    @allure.title("修改参数无效 {body} → 400 / 40001")
    def test_update_validation(self, tickets, api, body):
        t = tickets.create()
        api.put(f"/api/tickets/{t['id']}", body).expect.error(400, 40001)

    @allure.title("删除:ADMIN 逻辑删除后详情 404、列表不再出现;库里 deleted=1 行还在")
    def test_delete_is_logical(self, tickets, api, db):
        t = tickets.create()
        api.delete_ticket(t["id"]).expect.ok()
        api.get_ticket(t["id"]).expect.error(404, 40401)
        assert t["id"] not in {r["id"] for r in api.list_tickets(page=1, size=200).data["records"]}
        assert db.ticket(t["id"])["deleted"] == 1

    @allure.title("删除不存在的工单 → 404;重复删除 → 404(逻辑删除后视为不存在)")
    def test_delete_missing_and_twice(self, tickets, api):
        api.delete_ticket(99999999).expect.error(404, 40401)
        t = tickets.create()
        api.delete_ticket(t["id"]).expect.ok()
        api.delete_ticket(t["id"]).expect.error(404, 40401)


@allure.story("审计轨迹一致性")
class TestAudit:

    @allure.title("每一次状态变更恰好一条审计;operator 与请求方一致;from/to 与响应一致;traceId 与请求头一致")
    def test_audit_matches_every_transition(self, tickets, api, db):
        t = tickets.pending(group_id=1)
        steps = [
            (Users.LEADER_1, "assign", dict(assignee_id=Users.AGENT_A.id), "PENDING", "ASSIGNED"),
            (Users.AGENT_A, "transit", dict(target="PROCESSING"), "ASSIGNED", "PROCESSING"),
            (Users.AGENT_A, "transit", dict(target="WAIT_CONFIRM"), "PROCESSING", "WAIT_CONFIRM"),
            (Users.LEADER_1, "transit", dict(target="CLOSED"), "WAIT_CONFIRM", "CLOSED"),
        ]
        traces = []
        for i, (user, op, kw, src, dst) in enumerate(steps):
            trace = f"qa-audit-{t['id']}-{i}"
            client = api.as_user(user)
            if op == "assign":
                resp = client.request("POST", f"/api/tickets/{t['id']}/assign", json_body={"assigneeId": kw["assignee_id"]},
                                      headers={"X-Trace-Id": trace})
            else:
                resp = client.request("POST", f"/api/tickets/{t['id']}/transitions", json_body={"target": kw["target"]},
                                      headers={"X-Trace-Id": trace})
            resp.expect.ok().data("status").eq(dst)
            traces.append((user, src, dst, trace))

        logs = db.audit_logs(t["id"])
        assert len(logs) == 1 + len(steps)
        assert logs[0]["source"] == "LLM" and logs[0]["from_status"] is None
        for log, (user, src, dst, trace) in zip(logs[1:], traces):
            assert (log["from_status"], log["to_status"]) == (src, dst)
            assert log["operator_id"] == user.id and log["source"] == "MANUAL"
            assert log["trace_id"] == trace
        # 审计接口与库表一致
        api_logs = api.audit_logs(t["id"]).expect.ok().resp.data
        assert [(l.get("fromStatus"), l["toStatus"]) for l in api_logs] == [(l["from_status"], l["to_status"]) for l in logs]

    @allure.title("审计只读:AGENT 看不到别人工单的审计(403),组长可看本组")
    def test_audit_permission(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_B).audit_logs(t["id"]).expect.error(403, 40301)
        api.as_user(Users.LEADER_1).audit_logs(t["id"]).expect.ok()
        api.as_user(Users.LEADER_2).audit_logs(t["id"]).expect.error(403, 40301)
