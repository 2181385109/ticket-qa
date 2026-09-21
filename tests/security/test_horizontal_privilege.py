"""
水平越权(IDOR):角色够、但不是你的单——AGENT 用自己的 token 访问别人的工单(CLAUDE.md §5.6)。

判定表法:对每一个带 {id} 的接口,用"同组其他坐席 / 跨组坐席 / 跨组组长"三个身份各打一次,
期望全部 403 / 40301(区别于 40302,说明是身份不对而不是角色不够)。
校验在 Service 层(ADR-007),所以这里顺带证明:绕过 Controller 层的写法(直接换路径、换方法)也拦得住。
"""
import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("安全"), allure.story("水平越权")]

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"\x00" * 32

# 所有以工单 id 为对象的接口:name, 发起函数
ENDPOINTS = [
    ("GET 详情", lambda c, tid: c.get_ticket(tid)),
    ("PUT 修改", lambda c, tid: c.update_ticket(tid, "hijack", "hijack")),
    ("POST 流转", lambda c, tid: c.transit(tid, "PROCESSING")),
    ("GET 审计", lambda c, tid: c.audit_logs(tid)),
    ("POST 回复草稿", lambda c, tid: c.reply_draft(tid)),
    ("POST 上传附件", lambda c, tid: c.upload(tid, "x.png", PNG, "image/png")),
    ("GET 附件列表", lambda c, tid: c.list_attachments(tid)),
]
INTRUDERS = [Users.AGENT_B, Users.AGENT_C, Users.LEADER_2]


@pytest.fixture(scope="module")
def victim_ticket(module_factory):
    """agent_a 名下、1 组、ASSIGNED 的工单——被越权访问的目标"""
    return module_factory.assigned(Users.AGENT_A)


@pytest.mark.parametrize("intruder", INTRUDERS, ids=lambda u: u.username)
@pytest.mark.parametrize("name, call", ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
@allure.title("{intruder} 访问 agent_a 的工单:{name} → 403 / 40301")
def test_every_endpoint_rejects_non_owner(api, db, victim_ticket, intruder, name, call):
    audits = len(db.audit_logs(victim_ticket["id"]))
    call(api.as_user(intruder), victim_ticket["id"]).expect.error(403, 40301)
    # 越权尝试没有产生任何副作用
    row = db.ticket(victim_ticket["id"])
    assert row["status"] == "ASSIGNED" and row["assignee_id"] == Users.AGENT_A.id and row["title"] != "hijack"
    assert len(db.audit_logs(victim_ticket["id"])) == audits
    assert db.attachments(victim_ticket["id"]) == []


@allure.title("对照组:本人和本组组长、ADMIN 都能访问")
def test_owner_leader_admin_allowed(api, victim_ticket):
    for user in (Users.AGENT_A, Users.LEADER_1, Users.ADMIN):
        api.as_user(user).get_ticket(victim_ticket["id"]).expect.ok().data("id").eq(victim_ticket["id"])


@allure.title("同组 PENDING 单:坐席不能读(没分配给自己就不是你的),但能抢;抢完就是你的")
def test_pending_ticket_visibility(api, tickets):
    t = tickets.pending(group_id=1)
    api.as_user(Users.AGENT_B).get_ticket(t["id"]).expect.error(403, 40301)
    api.as_user(Users.AGENT_B).grab(t["id"]).expect.ok()
    api.as_user(Users.AGENT_B).get_ticket(t["id"]).expect.ok()
    api.as_user(Users.AGENT_A).get_ticket(t["id"]).expect.error(403, 40301)


@allure.title("跨组组长对别组工单:读 / 写 / 改派 全部 40301")
def test_cross_group_leader(api, tickets):
    t = tickets.assigned(Users.AGENT_A)
    leader2 = api.as_user(Users.LEADER_2)
    leader2.get_ticket(t["id"]).expect.error(403, 40301)
    leader2.transit(t["id"], "PROCESSING").expect.error(403, 40301)
    leader2.assign(t["id"], Users.AGENT_C.id).expect.error(403, 40301)


@allure.title("ID 枚举:坐席遍历相邻 id 只能打开自己的那一张,其余 403 或 404,没有信息泄露(403 响应不含标题)")
def test_id_enumeration_sweep(api, tickets):
    mine = tickets.assigned(Users.AGENT_A)
    others = [tickets.assigned(Users.AGENT_B)["id"], tickets.pending(group_id=2)["id"], tickets.assigned(Users.AGENT_C)["id"]]
    agent = api.as_user(Users.AGENT_A)
    for tid in range(min(others + [mine["id"]]) - 2, max(others + [mine["id"]]) + 3):
        resp = agent.get_ticket(tid)
        if tid == mine["id"]:
            resp.expect.ok()
        else:
            assert resp.status in (403, 404), resp.summary()
            assert resp.data is None
            assert "title" not in resp.text


@allure.title("列表接口不是越权通道:AGENT 的列表里只有自己的工单 id")
def test_list_does_not_leak(api, tickets):
    mine = tickets.assigned(Users.AGENT_A)
    other = tickets.assigned(Users.AGENT_B)
    ids = {r["id"] for r in api.as_user(Users.AGENT_A).list_tickets(page=1, size=200).data["records"]}
    assert mine["id"] in ids and other["id"] not in ids
    # status 过滤参数不能扩大范围
    ids2 = {r["id"] for r in api.as_user(Users.AGENT_A).list_tickets(status="ASSIGNED", page=1, size=200).data["records"]}
    assert other["id"] not in ids2
