"""
熔断——场景法:连续失败 5 次 → 打开 60 秒 → 期间直接走规则(不发请求)→ 到期自动恢复。

这个文件被 conftest 排到整个会话最后(circuit 标记):它会让所有 LLM 调用降级 60 秒。
模块开始前先等熔断器处于闭合(上一次运行可能刚打开过),结束后等它恢复,不给下一次运行留尾巴。
熔断器的状态用 llm_circuit_state 指标观测(1=打开 0=闭合)——这是接口层面唯一能看到熔断器的地方。
"""
import time

import allure
import pytest

from framework.users import Users
from framework.waits import wait_until

pytestmark = [allure.feature("LLM 路径"), allure.story("熔断"), pytest.mark.llm, pytest.mark.circuit, pytest.mark.slow,
              pytest.mark.db]

CLASSIFY_PATH = "/mock/llm/classify"


def _circuit_state(metrics) -> float:
    return metrics.value("llm_circuit_state")


@pytest.fixture(scope="module", autouse=True)
def circuit_closed_before_and_after(metrics, config, api, db):
    wait_until(lambda: _circuit_state(metrics), lambda v: v == 0, timeout=config.circuit_open_seconds + 5, interval=2,
               what="熔断器闭合(模块开始前)")
    # 清零连续失败计数:一次正常调用
    resp = api.create_ticket("streak reset before circuit " + "abcdef", "x")
    resp.expect.created()
    db.hard_delete_tickets([resp.data["id"]])
    yield
    wait_until(lambda: _circuit_state(metrics), lambda v: v == 0, timeout=config.circuit_open_seconds + 5, interval=2,
               what="熔断器闭合(模块结束后)")


class TestCircuitBreaker:

    @allure.title("连续 5 次 [ERROR]:前 4 次熔断仍闭合,第 5 次打开;llm_circuit_open_total +1,llm_circuit_state=1")
    def test_five_failures_open_the_circuit(self, tickets, metrics, metrics_before, config):
        for i in range(1, config.circuit_failure_threshold):
            tickets.create(title=tickets.title(f"[ERROR] 第{i}次"), content="x")
            assert _circuit_state(metrics) == 0, f"第 {i} 次失败后不应打开"
        assert metrics.delta(metrics_before, "llm_circuit_open_total") == 0

        tickets.create(title=tickets.title("[ERROR] 第5次"), content="x")

        assert _circuit_state(metrics) == 1
        assert metrics.delta(metrics_before, "llm_circuit_open_total", scene="CLASSIFY") == 1
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="CLASSIFY", reason="UPSTREAM_ERROR") == config.circuit_failure_threshold

    @allure.title("熔断打开期间:正常标题也降级 CIRCUIT_OPEN、latency=0、挡板收不到请求;草稿同样被短路(两个场景共用熔断器)")
    def test_open_circuit_short_circuits_everything(self, tickets, api, db, metrics, metrics_before, clean_wiremock_requests):
        assert _circuit_state(metrics) == 1, "前置:熔断器应处于打开"
        title = tickets.title("申请退款")
        resp = api.create_ticket(title, "熔断期间")
        resp.expect.created().data("category").eq("REFUND").data("priority").eq("P1").elapsed_lt(1500)
        tickets.track(resp.data["id"])

        row = db.llm_call(resp.data["id"])
        assert row["degraded"] == 1 and row["degrade_reason"] == "CIRCUIT_OPEN", row
        assert row["response_model"] is None and row["latency_ms"] == 0
        assert clean_wiremock_requests.count(CLASSIFY_PATH, body_contains=title) == 0, "熔断期间不应向挡板发请求"
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="CLASSIFY", reason="CIRCUIT_OPEN") == 1

        draft = api.reply_draft(resp.data["id"])
        draft.expect.ok().data("degraded").eq(True).data("degradeReason").eq("CIRCUIT_OPEN").data("latencyMs").eq(0)
        assert clean_wiremock_requests.count("/mock/llm/draft") == 0
        assert metrics.delta(metrics_before, "llm_fallback_total", scene="DRAFT_REPLY", reason="CIRCUIT_OPEN") == 1

    @allure.title("依赖已恢复但仍在降级(问题清单第 12 条):熔断打开 30 秒后挡板明明健康,分类仍 CIRCUIT_OPEN、挡板收不到请求——open-seconds 是定值不探测(ADR-004 接受的代价)")
    def test_still_degraded_while_dependency_is_healthy(self, tickets, api, db, metrics, config, wiremock, clean_wiremock_requests):
        assert _circuit_state(metrics) == 1, "前置:熔断器应处于打开"
        opened_at = time.monotonic()
        # 挡板本身是健康的:直连它就能拿到正常分类
        import json
        import requests
        # 挡板的桩用正则匹配原始请求体里的中文,所以要发 UTF-8 原文(requests 的 json= 会把中文转成 \uXXXX 转义)
        direct = requests.post(f"{config.wiremock_url}{CLASSIFY_PATH}",
                               data=json.dumps({"title": "申请退款", "content": "x"}, ensure_ascii=False).encode("utf-8"),
                               headers={"Content-Type": "application/json; charset=utf-8"}, timeout=5)
        assert direct.status_code == 200 and direct.json().get("category") == "REFUND", direct.text

        time.sleep(min(30, config.circuit_open_seconds / 2))
        assert _circuit_state(metrics) == 1, "半个窗口后仍应打开"
        title = tickets.title("申请退款")
        t = tickets.create(title=title, content="依赖已恢复但仍在窗口内")
        row = db.llm_call(t["id"])
        assert row["degrade_reason"] == "CIRCUIT_OPEN", row
        assert clean_wiremock_requests.count(CLASSIFY_PATH, body_contains=title) == 0, "窗口内不做任何试探"
        allure.attach(f"挡板健康、熔断打开 {time.monotonic() - opened_at:.0f}s 后仍降级;最坏情况依赖恢复后再降级 {config.circuit_open_seconds}s",
                      name="恢复后的固定降级时长", attachment_type=allure.attachment_type.TEXT)

    @allure.title("60 秒后自动恢复:llm_circuit_state 回到 0,正常标题重新由模型分类(degraded=0),挡板收到请求")
    def test_recovers_after_open_window(self, tickets, api, db, metrics, config, clean_wiremock_requests):
        t0 = time.monotonic()
        wait_until(lambda: _circuit_state(metrics), lambda v: v == 0, timeout=config.circuit_open_seconds + 5, interval=2,
                   what="熔断器自动闭合")
        allure.attach(f"等待了 {time.monotonic() - t0:.1f}s", name="恢复等待", attachment_type=allure.attachment_type.TEXT)

        title = tickets.title("申请退款")
        t = tickets.create(title=title, content="恢复后")
        row = db.llm_call(t["id"])
        assert row["degraded"] == 0 and row["response_model"] == "mock-classifier-v1", row
        assert clean_wiremock_requests.count(CLASSIFY_PATH, body_contains=title) == 1
        assert _circuit_state(metrics) == 0

    @allure.title("恢复后没有半开:再连续失败 4 次仍闭合(计数从 0 重新累)")
    def test_no_half_open_state(self, tickets, metrics, config):
        assert _circuit_state(metrics) == 0
        for i in range(1, config.circuit_failure_threshold):
            tickets.create(title=tickets.title(f"[ERROR] 恢复后第{i}次"), content="x")
            assert _circuit_state(metrics) == 0
        # 收尾:一次成功把计数清零,避免留给下一轮
        tickets.create(title=tickets.title("清零"), content="x")
        assert _circuit_state(metrics) == 0
