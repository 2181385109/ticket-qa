"""
SQL 注入探测——等价类划分:注入点分三类(JSON 字符串字段 / 查询参数 / 路径参数),
每类各取经典载荷。MyBatis-Plus 全部走预编译 #{},预期:字符串原样存取、参数类型不对直接 400、不存在 500、表不被破坏。

判定依据:
  1. 响应不是 500(注入没有引发 SQL 语法错误)
  2. 载荷被当作普通文本原样存回来(没有被"执行")
  3. 前后 ticket 总数只增加了本用例创建的数量(没有 DROP / DELETE 生效)
  4. 种子坐席仍是 6 个
"""
import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("安全"), allure.story("SQL 注入")]

STRING_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE ticket; --",
    "\" OR 1=1 --",
    "1; DELETE FROM agent WHERE 1=1; --",
    "' UNION SELECT username, display_name, role, group_id, active, created_at, updated_at FROM agent --",
    "admin'--",
    "%27%20OR%201%3D1",
    "\\' OR 1=1 #",
    "' AND SLEEP(5) --",
    "0x27204f522031",
]


@pytest.mark.parametrize("payload", STRING_PAYLOADS, ids=[f"p{i}" for i in range(len(STRING_PAYLOADS))])
@allure.title("标题 / 内容里的载荷「{payload}」被当作普通文本:201、原样返回、表数量不变")
def test_string_fields_are_parameterised(api, db, tickets, payload):
    total_before = db.count_tickets()
    resp = api.create_ticket(payload, payload, customer_id=1001)
    resp.expect.created().data("title").eq(payload).data("content").eq(payload).elapsed_lt(4000)
    tickets.track(resp.data["id"])
    assert db.ticket(resp.data["id"])["title"] == payload
    assert db.count_tickets() == total_before + 1
    assert db.scalar("SELECT COUNT(*) AS c FROM agent") == 6
    # 修改接口同样是参数化的
    api.update_ticket(resp.data["id"], payload + "x", payload).expect.ok().data("title").eq(payload + "x")


@pytest.mark.parametrize("status", ["PENDING' OR '1'='1", "PENDING;DROP TABLE ticket", "PENDING UNION SELECT 1", "1=1"],
                         ids=["quote-or", "semicolon", "union", "bare"])
@allure.title("列表 status 参数注入「{status}」→ 400(枚举转换拒绝),不是 500")
def test_status_param_is_enum_bound(api, status):
    api.list_tickets(status=status, page=1, size=10).expect.error(400, 40001)


@pytest.mark.parametrize("raw_id", ["1 OR 1=1", "1'", "-1", "9999999999999999999999", "1.0", "1%00"],
                         ids=["or", "quote", "negative", "overflow", "float", "nul"])
@allure.title("路径参数 id 注入「{raw_id}」→ 400 或 404,不是 500")
def test_path_id_is_typed(api, raw_id):
    resp = api.get(f"/api/tickets/{raw_id}")
    assert resp.status in (400, 404), resp.summary()
    # %00 由 Tomcat 在进入 Spring 之前就拒绝,返回的是容器的 HTML 400、没有统一信封——这是容器层行为,记录为观察项
    assert resp.code in (40001, 40401) or (resp.status == 400 and resp.code is None), resp.summary()


@pytest.mark.parametrize("suffix", [";DROP TABLE ticket", "%0a", "%20"], ids=["semicolon-matrix", "trailing-newline", "trailing-space"])
@allure.title("路径参数尾巴「{suffix}」被框架剥掉 / 去空白,等价于原 id:不执行、不报错、表不变(观察项,不是漏洞)")
def test_path_id_tolerated_suffixes(api, db, tickets, suffix):
    t = tickets.create()
    total = db.count_tickets()
    resp = api.get(f"/api/tickets/{t['id']}{suffix}")
    assert resp.status in (200, 400, 404), resp.summary()
    if resp.status == 200:
        resp.expect.data("id").eq(t["id"])
    assert db.count_tickets() == total


@pytest.mark.parametrize("params", [{"page": "1 OR 1=1"}, {"size": "10; DROP TABLE ticket"}, {"page": "1'"}],
                         ids=["page-or", "size-drop", "page-quote"])
@allure.title("分页参数注入 {params} → 400")
def test_paging_params_are_typed(api, params):
    api.list_tickets(**params).expect.error(400, 40001)


@allure.title("assigneeId 注入 → 400(Long 类型绑定)")
def test_assignee_id_is_typed(api, tickets):
    t = tickets.pending(group_id=1)
    api.as_user(Users.LEADER_1).post(f"/api/tickets/{t['id']}/assign", {"assigneeId": "3 OR 1=1"}).expect.error(400, 40001)


@allure.title("X-User-Id 头注入 → 401(解析成 Long 失败),不会变成别的用户")
def test_user_header_injection(api):
    for raw in ["3 OR 1=1", "3' --", "1; DROP TABLE agent"]:
        api.request("GET", "/api/agents/me", headers={"X-User-Id": raw}, user=None).expect.error(401, 40101)


@allure.title("时间盲注探测:含 SLEEP(5) 的载荷不会让响应变慢")
def test_no_time_based_injection(api, tickets):
    resp = api.create_ticket("x' AND SLEEP(5) AND 'a'='a", "content' OR SLEEP(5) #", customer_id=1001)
    resp.expect.created().elapsed_lt(4000)
    tickets.track(resp.data["id"])
    api.list_tickets(page=1, size=10).expect.ok().elapsed_lt(4000)
