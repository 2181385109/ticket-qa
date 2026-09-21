"""
LLM 路径 · 分类(第一个调用点)——判定表法(docs/test-design/03)。

固定断言项(docs/findings/20260920 的教训):
  正常路径不只断"分类在枚举内",必须断 llm_call_log.degraded=0 且 response_model 非空、raw_category 与最终一致;
  否则"契约满足"可能只是关键词规则兜底的副产品,整条 LLM 路径失效了也看不出来。
降级路径则相反:degraded=1、response_model 为空、degrade_reason 精确到枚举值、指标按 reason 打点,
并且到挡板那边核对"服务到底有没有把请求发出去"。

每个降级用例结束后做一次正常分类,把熔断器的连续失败计数清零——否则跨用例累计 5 次会把熔断打开,
污染后面所有用例(熔断本身的用例在 test_llm_circuit.py,排在最后跑)。
"""
import allure
import pytest

from framework.factory import CATEGORIES, PRIORITIES
from framework.users import Users

pytestmark = [allure.feature("LLM 路径"), pytest.mark.llm, pytest.mark.db]

CLASSIFY_PATH = "/mock/llm/classify"


@pytest.fixture
def reset_streak(tickets):
    """降级用例的收尾:一次成功调用把 CircuitBreaker.consecutiveFailures 归零"""
    yield
    tickets.create(title=tickets.title("streak reset"), content="正常")


def _assert_not_degraded(db, ticket, expected_category: str, expected_priority: str):
    row = db.llm_call(ticket["id"], "CLASSIFY")
    assert row["degraded"] == 0, f"LLM 路径实际降级了: {row}"
    assert row["degrade_reason"] is None
    assert row["response_model"] == "mock-classifier-v1", row
    assert row["request_model"] == "mock-classifier-v1"
    assert row["raw_category"] == expected_category and row["final_category"] == expected_category
    assert row["contract_violated"] == 0
    assert row["scene"] == "CLASSIFY" and row["trace_id"] not in (None, "-")
    assert ticket["category"] == expected_category and ticket["priority"] == expected_priority


@allure.story("正常路径:挡板按关键词分类,服务原样采用")
class TestNormalClassification:

    @pytest.mark.parametrize("keyword, category, priority", [
        ("申请退款", "REFUND", "P1"),
        ("账单有误", "BILLING", "P1"),
        ("登录报错", "TECH", "P0"),
        ("咨询会员权益", "OTHER", "P2"),
    ], ids=["REFUND", "BILLING", "TECH", "OTHER"])
    @allure.title("「{keyword}」→ {category}/{priority},且 llm_call_log 证明是模型给的(degraded=0, response_model 非空)")
    def test_keyword_routes(self, tickets, db, clean_wiremock_requests, keyword, category, priority):
        title = tickets.title(keyword)
        t = tickets.create(title=title, content="自动化")
        _assert_not_degraded(db, t, category, priority)
        # 挡板确实收到了这一次请求,且请求体里带了标题(不是空 body——h2c 问题的直接检验)
        reqs = clean_wiremock_requests.requests_to(CLASSIFY_PATH, body_contains=title)
        assert len(reqs) == 1, f"挡板应收到恰好 1 个带该标题的请求,实际 {len(reqs)}"
        assert reqs[0]["headers"].get("Content-Type", "").startswith("application/json")

    @allure.title("同时命中两类关键词:挡板给的仍是枚举内的值且不降级(挡板同优先级桩的取舍不是规格,不断言具体类别)")
    def test_ambiguous_keywords(self, tickets, db):
        t = tickets.create(title=tickets.title("退款和账单都有问题"), content="x")
        assert t["category"] in ("REFUND", "BILLING")
        _assert_not_degraded(db, t, t["category"], "P1")

    @allure.title("耗时:正常路径远低于 3 秒超时阈值,latency_ms 如实记录")
    def test_latency_recorded(self, tickets, db, api):
        title = tickets.title("咨询")
        resp = api.create_ticket(title, "x")
        resp.expect.created().elapsed_lt(2500)
        tickets.track(resp.data["id"])
        row = db.llm_call(resp.data["id"])
        assert 0 <= row["latency_ms"] < 2500


@allure.story("降级路径:超时 / 上游错误 / 响应格式错误 → 规则")
class TestDegradation:

    @pytest.mark.slow
    @allure.title("[SLOW] 挡板延迟 5s → 服务 3s 超时 → TIMEOUT 降级,规则分类 REFUND/P1,耗时 ≥ 3000ms,挡板收到了请求")
    def test_timeout_falls_back_to_rules(self, tickets, api, db, metrics, metrics_before, clean_wiremock_requests,
                                         reset_streak, config):
        title = tickets.title("[SLOW] 退款申请")
        resp = api.create_ticket(title, "慢响应")
        resp.expect.created().elapsed_ge(config.llm_timeout_ms).data("category").eq("REFUND").data("priority").eq("P1")
        tickets.track(resp.data["id"])

        row = db.llm_call(resp.data["id"])
        assert row["degraded"] == 1 and row["degrade_reason"] == "TIMEOUT", row
        assert row["response_model"] is None and row["raw_category"] is None
        assert row["latency_ms"] >= config.llm_timeout_ms
        assert row["final_category"] == "REFUND"
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="CLASSIFY", reason="TIMEOUT") == 1
        assert metrics.delta(metrics_before, "llm_call_duration_seconds_count", scene="CLASSIFY", outcome="failure_timeout") == 1
        assert clean_wiremock_requests.count(CLASSIFY_PATH, body_contains=title) == 1, "超时是等不到响应,请求本身应已发出"
        # 审计备注记录了降级
        first = db.audit_logs(resp.data["id"])[0]
        assert "degraded=true" in first["remark"] and "TIMEOUT" in first["remark"]

    @allure.title("[ERROR] 挡板 500 → UPSTREAM_ERROR 降级,规则分类 TECH/P0(「登录报错 紧急」)")
    def test_upstream_error_falls_back(self, tickets, db, metrics, metrics_before, reset_streak):
        t = tickets.create(title=tickets.title("[ERROR] 登录报错 紧急"), content="x")
        assert (t["category"], t["priority"]) == ("TECH", "P0")
        row = db.llm_call(t["id"])
        assert row["degraded"] == 1 and row["degrade_reason"] == "UPSTREAM_ERROR"
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="CLASSIFY", reason="UPSTREAM_ERROR") == 1

    @allure.title("[BAD_JSON] 挡板返回非 JSON → BAD_RESPONSE 降级,规则分类")
    def test_bad_json_falls_back(self, tickets, db, metrics, metrics_before, reset_streak):
        t = tickets.create(title=tickets.title("[BAD_JSON] 发票开错了"), content="x")
        assert (t["category"], t["priority"]) == ("BILLING", "P1")
        row = db.llm_call(t["id"])
        assert row["degraded"] == 1 and row["degrade_reason"] == "BAD_RESPONSE"
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="CLASSIFY", reason="BAD_RESPONSE") == 1

    @allure.title("降级结果仍在枚举内;注意 [ERROR] 标记本身含 error,会被关键词规则算成 TECH/P1")
    def test_degraded_result_stays_in_contract(self, tickets, reset_streak):
        t = tickets.create(title=tickets.title("[ERROR] 随便问问"), content="不含任何关键词")
        assert t["category"] in CATEGORIES and t["priority"] in PRIORITIES
        assert (t["category"], t["priority"]) == ("TECH", "P1"), "规则:error 命中 TECH,无 P0 词 → P1"


@allure.story("契约校验:越界枚举")
class TestContractViolation:

    @allure.title("[BAD_CATEGORY] 挡板返回 SPAM → 落 OTHER;这不是降级(degraded=0),但 contract_violated=1、raw_category=SPAM、指标 +1")
    def test_out_of_enum_category(self, tickets, db, metrics, metrics_before):
        t = tickets.create(title=tickets.title("[BAD_CATEGORY] 账单问题"), content="越界分类")
        assert t["category"] == "OTHER"
        assert t["priority"] == "P1", "优先级挡板给的是 P1,在枚举内,应保留"
        row = db.llm_call(t["id"])
        assert row["degraded"] == 0 and row["degrade_reason"] is None
        assert row["contract_violated"] == 1
        assert row["raw_category"] == "SPAM" and row["final_category"] == "OTHER"
        assert row["response_model"] == "mock-classifier-v1"
        assert metrics.delta(metrics_before, "llm_contract_violation_total", scene="CLASSIFY", field="category") == 1
        assert metrics.delta(metrics_before, "llm_fallback_total") == 0
        assert "contractViolated=true" in db.audit_logs(t["id"])[0]["remark"]

    @allure.title("临时桩:优先级越界(P9)→ 分类采用挡板的,优先级由规则兜底,指标 field=priority +1")
    def test_out_of_enum_priority_via_temp_stub(self, tickets, db, metrics, metrics_before, wiremock):
        marker = "[BAD_PRIORITY-" + tickets.title("")[1:] + "]"
        stub_id = wiremock.add_stub({
            "priority": 1,
            "request": {"method": "POST", "urlPath": CLASSIFY_PATH,
                        "bodyPatterns": [{"matchesJsonPath": {"expression": "$.title", "contains": marker}}]},
            "response": {"status": 200, "headers": {"Content-Type": "application/json"},
                         "jsonBody": {"model": "mock-classifier-v1", "category": "BILLING", "priority": "P9"}},
        })
        try:
            t = tickets.create(title=f"{marker} 紧急 账单", content="x")
        finally:
            wiremock.delete_stub(stub_id)
        assert t["category"] == "BILLING"
        assert t["priority"] == "P0", "规则:命中「紧急」→ P0"
        row = db.llm_call(t["id"])
        assert row["degraded"] == 0 and row["contract_violated"] == 1
        assert metrics.delta(metrics_before, "llm_contract_violation_total", scene="CLASSIFY", field="priority") == 1


@allure.story("回复草稿(第二个调用点)")
class TestDraftReply:

    @allure.title("正常:草稿来自模型(degraded=false, responseModel=mock-writer-v1),内容回填了标题;llm_call_log scene=DRAFT_REPLY 绑定工单")
    def test_normal_draft(self, tickets, api, db):
        t = tickets.assigned(Users.AGENT_A)
        resp = api.as_user(Users.AGENT_A).reply_draft(t["id"])
        (resp.expect.ok()
         .data("ticketId").eq(t["id"])
         .data("degraded").eq(False)
         .lacks_keys("degradeReason")
         .data("requestModel").eq("mock-classifier-v1")
         .data("responseModel").eq("mock-writer-v1")
         .data("draft").contains(t["title"])
         .data("draft").contains(t["category"])
         .data("latencyMs").ge(0))
        row = db.llm_call(t["id"], "DRAFT_REPLY")
        assert row["degraded"] == 0 and row["response_model"] == "mock-writer-v1"

    @pytest.mark.slow
    @allure.title("[SLOW] 工单的草稿超时 → 模板草稿,degraded=true reason=TIMEOUT,模板含标题与分类")
    def test_timeout_draft_uses_template(self, tickets, api, db, metrics, metrics_before, reset_streak):
        t = tickets.create(title=tickets.title("[SLOW] 退款申请"), content="x")   # 创建本身也会超时降级
        resp = api.reply_draft(t["id"])
        (resp.expect.ok()
         .data("degraded").eq(True)
         .data("degradeReason").eq("TIMEOUT")
         .lacks_keys("responseModel")
         .data("draft").contains(t["title"])
         .data("draft").contains("REFUND")
         .data("latencyMs").ge(3000)
         .elapsed_ge(3000))
        assert db.llm_call(t["id"], "DRAFT_REPLY")["degrade_reason"] == "TIMEOUT"
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="DRAFT_REPLY", reason="TIMEOUT") == 1

    @allure.title("[ERROR] 工单的草稿 500 → UPSTREAM_ERROR 模板")
    def test_upstream_error_draft(self, tickets, api, reset_streak):
        t = tickets.create(title=tickets.title("[ERROR] 登录报错"), content="x")
        api.reply_draft(t["id"]).expect.ok().data("degraded").eq(True).data("degradeReason").eq("UPSTREAM_ERROR")

    @allure.title("草稿需要写权限:别的坐席 → 403 / 40301;组长 / ADMIN 可以")
    def test_draft_permission(self, tickets, api):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_B).reply_draft(t["id"]).expect.error(403, 40301)
        api.as_user(Users.LEADER_1).reply_draft(t["id"]).expect.ok()
        api.reply_draft(t["id"]).expect.ok()
