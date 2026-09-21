"""
LLM 第二个调用点(回复草稿)的降级路径——故障注入时只打了创建时的分类(问题清单第 8 条)。

草稿路径和分类路径共用 LlmService 的超时 / 熔断 / 落盘外壳(ADR-004),但输入不同(标题 + 内容 + 分类)、
挡板桩也是另一组(ops/wiremock/mappings/llm-draft.json),所以每条降级都要在这条路径上单独验一次。

隔离技巧:先用正常标题创建(分类路径不降级、不给熔断器计数),再用 PUT 把标题改成带故障标记的
(修改标题不调 LLM),然后调 reply-draft——这样观察到的降级 / 失败计数只来自草稿路径。
"""
import allure
import pytest

from framework.users import Users
from framework.waits import wait_until

pytestmark = [allure.feature("LLM 路径"), allure.story("回复草稿降级"), pytest.mark.llm, pytest.mark.db]

DRAFT_PATH = "/mock/llm/draft"


def _retitle(api, tickets, marker: str) -> dict:
    t = tickets.assigned(Users.AGENT_A)
    api.as_user(Users.AGENT_A).update_ticket(t["id"], f"{marker} 退款问题 {tickets.title('')}", "订单重复扣款").expect.ok()
    return t


class TestDraftDegradation:

    @allure.title("[SLOW] 草稿:3 秒超时 → degraded=TIMEOUT、模板草稿、latencyMs≈3000、llm_call_log scene=DRAFT_REPLY、fallback{DRAFT_REPLY,TIMEOUT}+1")
    @pytest.mark.slow
    def test_draft_timeout_falls_back_to_template(self, api, tickets, db, config, metrics, metrics_before, clean_wiremock_requests):
        t = _retitle(api, tickets, "[SLOW]")
        resp = api.as_user(Users.AGENT_A).reply_draft(t["id"])
        (resp.expect.ok().data("degraded").eq(True).data("degradeReason").eq("TIMEOUT")
         .data("draft").contains("已收到您关于").data("responseModel").is_none()
         .data("latencyMs").ge(config.llm_timeout_ms - 50).elapsed_lt(config.llm_timeout_ms + 1500))
        row = db.llm_call(t["id"], scene="DRAFT_REPLY")
        assert row["degraded"] == 1 and row["degrade_reason"] == "TIMEOUT" and row["response_model"] is None
        assert row["request_model"] == "mock-classifier-v1"
        assert clean_wiremock_requests.count(DRAFT_PATH) == 1, "挡板确实收到了请求(是超时不是没发)"
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="DRAFT_REPLY", reason="TIMEOUT") == 1
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="CLASSIFY") == 0, "分类路径未受影响"

    @allure.title("[ERROR] 草稿:挡板 500 → degraded=UPSTREAM_ERROR,模板草稿,fallback{DRAFT_REPLY,UPSTREAM_ERROR}+1")
    def test_draft_upstream_error_falls_back(self, api, tickets, db, metrics, metrics_before):
        t = _retitle(api, tickets, "[ERROR]")
        resp = api.as_user(Users.AGENT_A).reply_draft(t["id"])
        resp.expect.ok().data("degraded").eq(True).data("degradeReason").eq("UPSTREAM_ERROR").elapsed_lt(1500)
        row = db.llm_call(t["id"], scene="DRAFT_REPLY")
        assert row["degrade_reason"] == "UPSTREAM_ERROR"
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="DRAFT_REPLY", reason="UPSTREAM_ERROR") == 1
        # 收尾:一次正常草稿把连续失败计数清零,不给后面的用例留尾巴
        api.as_user(Users.AGENT_A).update_ticket(t["id"], "恢复正常标题", "x").expect.ok()
        api.as_user(Users.AGENT_A).reply_draft(t["id"]).expect.ok().data("degraded").eq(False)


@pytest.mark.circuit
@pytest.mark.slow
@allure.story("草稿失败计入同一个熔断器")
class TestDraftSharesCircuit:
    """
    这个类会把熔断器打开 60 秒,conftest 把它排到 circuit 段;模块前后各等一次闭合,和 test_llm_circuit 同样的纪律。
    """

    @pytest.fixture(autouse=True)
    def circuit_closed(self, metrics, config, api, db):
        wait_until(lambda: metrics.value("llm_circuit_state"), lambda v: v == 0, timeout=config.circuit_open_seconds + 5,
                   interval=2, what="熔断器闭合(用例开始前)")
        resp = api.create_ticket("streak reset before draft circuit abcdef", "x")
        resp.expect.created()
        db.hard_delete_tickets([resp.data["id"]])
        yield
        wait_until(lambda: metrics.value("llm_circuit_state"), lambda v: v == 0, timeout=config.circuit_open_seconds + 5,
                   interval=2, what="熔断器闭合(用例结束后)")

    @allure.title("4 次草稿 [ERROR] + 1 次分类 [ERROR] = 5 次连续失败 → 熔断打开;打开后草稿 CIRCUIT_OPEN 且挡板收不到请求")
    def test_draft_and_classify_failures_share_one_breaker(self, api, tickets, metrics, metrics_before, config, clean_wiremock_requests):
        t = _retitle(api, tickets, "[ERROR]")
        agent = api.as_user(Users.AGENT_A)
        for i in range(1, config.circuit_failure_threshold):
            agent.reply_draft(t["id"]).expect.ok().data("degradeReason").eq("UPSTREAM_ERROR")
            assert metrics.value("llm_circuit_state") == 0, f"第 {i} 次草稿失败后不应打开"

        tickets.create(title=tickets.title("[ERROR] 第5次来自分类"), content="x")

        assert metrics.value("llm_circuit_state") == 1, "第 5 次失败(分类路径)把熔断器打开:两个场景共用一个计数"
        assert metrics.delta(metrics_before, "llm_circuit_open_total", scene="CLASSIFY") == 1
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="DRAFT_REPLY", reason="UPSTREAM_ERROR") == config.circuit_failure_threshold - 1

        clean_wiremock_requests.reset_requests()
        agent.reply_draft(t["id"]).expect.ok().data("degradeReason").eq("CIRCUIT_OPEN").data("latencyMs").eq(0)
        assert clean_wiremock_requests.count(DRAFT_PATH) == 0
