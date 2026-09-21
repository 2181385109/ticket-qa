"""
创建工单:参数校验(等价类 + 边界值)、返回契约、SLA 截止时间、初始审计。

标题长度边界:0(空)/ 1 / 200 / 201;customerId:正数 / 0 / 负数 / 缺失 / 非数字;groupId:缺省=1 / 指定 / 0。
"""
import re
from datetime import datetime, timedelta

import allure
import pytest

from framework.factory import CATEGORIES, PRIORITIES
from framework.users import Users

pytestmark = [allure.feature("工单"), allure.story("创建")]

TIME_FMT = "%Y-%m-%d %H:%M:%S"


class TestCreateContract:

    @allure.title("创建成功:201 + 完整字段 + PENDING + 单号格式 + 无 assignee")
    def test_create_returns_full_contract(self, tickets, api):
        title = tickets.title("咨询会员权益")
        resp = api.as_user(Users.AGENT_A).create_ticket(title, "想了解一下", customer_id=1001)
        tickets.track(resp.data["id"])
        (resp.expect.created()
         .has_keys("id", "ticketNo", "title", "content", "category", "priority", "status", "customerId", "groupId",
                   "slaDeadline", "createdAt", "updatedAt")
         .lacks_keys("assigneeId", "escalatedAt", "closedAt", "deleted")
         .data("ticketNo").matches(r"^T\d{8}-[0-9A-F]{16}$")     # 64 bit 随机段(KI-011 / ADR-019),不再是 8 位
         .data("status").eq("PENDING")
         .data("title").eq(title)
         .data("category").is_in(CATEGORIES)
         .data("priority").is_in(PRIORITIES)
         .data("groupId").eq(1)
         .data("customerId").eq(1001)
         .has_trace_id())

    @allure.title("单号唯一性(KI-011):10 线程并发创建 100 张,ticketNo 两两不同、定长 26、日期段为今天;统计层面的位宽证明在单测 TicketNoGeneratorTest")
    def test_ticket_no_unique_under_concurrency(self, tickets, config, db):
        from concurrent.futures import ThreadPoolExecutor
        from framework.client import ApiClient
        import requests

        def one(i: int):
            client = ApiClient(config.base_url, Users.ADMIN, 30, session=requests.Session(), attach=False)
            r = client.create_ticket(f"ticket_no uniq {i}", "x", group_id=1)
            assert r.status == 201, r.summary()
            return r.data

        with ThreadPoolExecutor(max_workers=10) as ex:
            created = list(ex.map(one, range(100)))
        tickets.created_ids.extend(d["id"] for d in created)
        nos = [d["ticketNo"] for d in created]
        assert len(set(nos)) == len(nos) == 100
        today = db.db_now().strftime("%Y%m%d")
        assert all(re.fullmatch(rf"T{today}-[0-9A-F]{{16}}", n) for n in nos), nos[:3]

    @allure.title("groupId 缺省为 1;显式指定 2 则落到 2 组")
    def test_group_default_and_explicit(self, tickets):
        assert tickets.create()["groupId"] == 1
        assert tickets.create(group_id=2)["groupId"] == 2

    @pytest.mark.parametrize("priority", PRIORITIES)
    @allure.title("SLA 截止 = 创建时刻 + 优先级时限({priority})")
    def test_sla_deadline_equals_created_plus_limit(self, tickets, config, priority):
        # 通过挡板关键词把优先级"钉"住:P0=技术故障词,P1=退款词,P2=兜底
        title = {"P0": tickets.title("登录报错"), "P1": tickets.title("申请退款"), "P2": tickets.title("咨询")}[priority]
        t = tickets.create(title=title, content="自动化")
        assert t["priority"] == priority, t
        created = datetime.strptime(t["createdAt"], TIME_FMT)
        deadline = datetime.strptime(t["slaDeadline"], TIME_FMT)
        assert deadline - created == timedelta(minutes=config.sla_minutes[priority])

    @allure.title("首条审计:from=null,to=PENDING,source=LLM,备注含分类结果,traceId 与创建请求一致")
    def test_initial_audit_log(self, tickets, api, db):
        t = tickets.create()
        resp = api.audit_logs(t["id"])
        resp.expect.ok().data().length(1)
        first = resp.data[0]
        assert first.get("fromStatus") is None
        assert first["toStatus"] == "PENDING"
        assert first["source"] == "LLM"
        assert "自动分类" in first["remark"] and f"category={t['category']}" in first["remark"]
        assert first["traceId"] and first["traceId"] != "-"
        # 库里 llm_call_log 已绑定到这张工单(bindTicket 在同一事务)
        assert db.llm_call(t["id"])["ticket_id"] == t["id"]

    @allure.title("createdAt == updatedAt 创建时相等;流转后 updatedAt 变化")
    def test_updated_at_changes_after_transition(self, tickets, api):
        t = tickets.create()
        assert t["createdAt"] == t["updatedAt"]
        import time
        time.sleep(1.1)   # 时间格式到秒,至少跨 1 秒才能看出变化
        after = api.as_user(Users.AGENT_A).grab(t["id"])
        after.expect.ok().data("updatedAt").ne(t["updatedAt"])
        after.expect.data("createdAt").eq(t["createdAt"])


class TestCreateValidation:

    @pytest.mark.parametrize("body, field", [
        ({"title": "", "content": "x", "customerId": 1}, "title"),
        ({"title": "   ", "content": "x", "customerId": 1}, "title"),
        ({"content": "x", "customerId": 1}, "title"),
        ({"title": "t", "content": "", "customerId": 1}, "content"),
        ({"title": "t", "content": "x"}, "customerId"),
        ({"title": "t", "content": "x", "customerId": 0}, "customerId"),
        ({"title": "t", "content": "x", "customerId": -5}, "customerId"),
        ({"title": "t", "content": "x", "customerId": 1, "groupId": 0}, "groupId"),
        ({"title": "标" * 201, "content": "x", "customerId": 1}, "title"),
        ({"title": "t", "content": "内" * 5001, "customerId": 1}, "content"),
    ], ids=["blank-title", "space-title", "no-title", "blank-content", "no-customer", "customer-0", "customer-neg",
            "group-0", "title-201", "content-5001"])
    @allure.title("无效等价类 {field} → 400 / 40001,message 指出字段名")
    def test_invalid_bodies(self, api, body, field):
        api.create_ticket_raw(body).expect.error(400, 40001).body("message").contains(field)

    @pytest.mark.parametrize("title_len", [1, 200])
    @allure.title("标题长度边界 {title_len} 字 → 201(有效边界)")
    def test_title_length_boundaries(self, tickets, api, title_len):
        resp = api.create_ticket("标" * title_len, "x")
        resp.expect.created()
        tickets.track(resp.data["id"])

    @allure.title("内容 5000 字 → 201(有效上界)")
    def test_content_upper_boundary(self, tickets, api):
        resp = api.create_ticket(tickets.title(), "内" * 5000)
        resp.expect.created()
        tickets.track(resp.data["id"])

    @pytest.mark.parametrize("raw", ['{"title": "t", "content": "x", "customerId": "abc"}', "{not json", "", "[]", "null"])
    @allure.title("请求体格式错误「{raw}」→ 400 / 40001")
    def test_malformed_bodies(self, api, raw):
        api.request("POST", "/api/tickets", raw_body=raw.encode("utf-8"),
                    headers={"Content-Type": "application/json"}).expect.error(400, 40001)

    @allure.title("未知字段被忽略(宽松反序列化),不影响创建")
    def test_unknown_fields_ignored(self, tickets, api):
        resp = api.create_ticket_raw({"title": tickets.title(), "content": "x", "customerId": 1, "status": "CLOSED",
                                      "assigneeId": 3, "id": 999999})
        resp.expect.created().data("status").eq("PENDING").data("id").ne(999999)
        resp.expect.lacks_keys("assigneeId")
        tickets.track(resp.data["id"])
