"""
冒烟 + 认证。
设计方法:等价类划分——X-User-Id 的输入域分成 缺失 / 非数字 / 不存在 / 存在 四类。
"""
import allure
import pytest

from framework.users import Users

pytestmark = [allure.feature("基础"), pytest.mark.smoke]


@allure.story("健康与指标")
class TestHealth:

    @allure.title("/actuator/health 为 UP 且 db / redis / rabbit 全 UP")
    def test_health_up(self, api):
        (api.health().expect.status(200)
         .body("status").eq("UP")
         .body("components.db.status").eq("UP")
         .body("components.redis.status").eq("UP")
         .body("components.rabbit.status").eq("UP"))

    @allure.title("/actuator/prometheus 暴露本项目在启动时就注册的自定义指标(含抢单三层防线的 4 个计数)")
    def test_custom_metrics_exposed(self, metrics):
        names = metrics.names()
        for expected in ("llm_circuit_state", "mq_event_published_total", "mq_event_consumed_total",
                         "mq_event_duplicate_total", "mq_event_publish_failed_total", "sla_scan_total",
                         "sla_escalated_total", "sla_escalation_skipped_total", "sla_scan_lock_unavailable_total",
                         "grab_lock_acquired_total", "grab_lock_rejected_total", "grab_lock_unavailable_total",
                         "grab_conflict_total", "ticket_version_conflict_total",
                         "http_server_requests_seconds"):
            assert any(n == expected or n.startswith(expected) for n in names), f"缺少指标 {expected}"

    @allure.title("带标签的 LLM 计数在首次发生前就以 0 存在(KI-007 / KI-015):2 场景 × 4 原因的 llm_fallback_total、circuit_open、contract_violation")
    def test_labelled_llm_counters_pre_registered(self, metrics):
        snap = metrics.snapshot()
        for scene in ("CLASSIFY", "DRAFT_REPLY"):
            for reason in ("TIMEOUT", "CIRCUIT_OPEN", "UPSTREAM_ERROR", "BAD_RESPONSE"):
                key = ("llm_fallback_total", frozenset({("scene", scene), ("reason", reason), ("application", "ticket-qa-service")}))
                assert key in snap, f"缺少 llm_fallback_total{{scene={scene},reason={reason}}}"
            assert any(n == "llm_circuit_open_total" and ("scene", scene) in pairs for (n, pairs) in snap)
            for field in ("category", "priority"):
                assert any(n == "llm_contract_violation_total" and ("scene", scene) in pairs and ("field", field) in pairs
                           for (n, pairs) in snap), f"缺少 llm_contract_violation_total{{scene={scene},field={field}}}"

    @allure.title("Tomcat 线程池指标已暴露(KI-016):busy / current / config_max,压测时不必再靠 Arthas 读")
    def test_tomcat_thread_metrics_exposed(self, metrics):
        snap = metrics.snapshot()
        busy = metrics._match(snap, "tomcat_threads_busy_threads", {})
        current = metrics._match(snap, "tomcat_threads_current_threads", {})
        maximum = metrics._match(snap, "tomcat_threads_config_max_threads", {})
        assert maximum == 200 and current >= 1 and 0 <= busy <= current, (busy, current, maximum)

    @allure.title("文件日志带 traceId(KI-016):用自定义 X-Trace-Id 创建工单后,日志文件里能按 [traceId] 找到那一行")
    def test_file_log_carries_trace_id(self, api, tickets, service_log):
        if not service_log.available:
            pytest.skip("SERVICE_LOG_PATH 不可用")
        offset = service_log.size()
        trace = "qa-filelog-" + tickets.title("")[1:]
        resp = api.request("POST", "/api/tickets", json_body={"title": "file log trace", "content": "x", "customerId": 1},
                           headers={"X-Trace-Id": trace})
        resp.expect.created()
        tickets.track(resp.data["id"])
        lines = service_log.lines_since(offset, f"[{trace}]")
        allure.attach("\n".join(lines), name="命中的日志行", attachment_type=allure.attachment_type.TEXT)
        assert any("工单创建" in ln and f"id={resp.data['id']}" in ln for ln in lines), lines

    @allure.title("Actuator 端点不需要 X-User-Id(拦截器只拦 /api/**)")
    def test_actuator_needs_no_auth(self, anon):
        anon.health().expect.status(200)


@allure.story("认证:X-User-Id")
class TestAuth:

    @allure.title("缺少 X-User-Id → 401 / 40101,统一错误格式")
    def test_missing_header(self, anon):
        anon.me().expect.error(401, 40101).envelope()

    @pytest.mark.parametrize("raw", ["abc", "", "3;DROP TABLE agent", "1e3", "-1", "0", "0x3", "3.0"])
    @allure.title("X-User-Id 非法值「{raw}」→ 401")
    def test_invalid_header_values(self, api, raw):
        api.request("GET", "/api/agents/me", headers={"X-User-Id": raw}, user=None).expect.error(401, 40101)

    @allure.title("X-User-Id 指向不存在的坐席 → 401")
    def test_unknown_user(self, api):
        api.as_user(Users.UNKNOWN_ID).me().expect.error(401, 40101)

    @pytest.mark.parametrize("user", Users.ALL, ids=lambda u: u.username)
    @allure.title("种子坐席 {user} 能认证,返回的角色 / 组与种子一致")
    def test_seed_users(self, api, user):
        (api.as_user(user).me().expect.ok()
         .data("id").eq(user.id)
         .data("username").eq(user.username)
         .data("role").eq(user.role)
         .data("groupId").eq(user.group_id)
         .has_trace_id())

    @allure.title("传入的 X-Trace-Id 被原样回带(接口测试与服务日志对账的依据)")
    def test_trace_id_passthrough(self, api):
        resp = api.request("GET", "/api/agents/me", headers={"X-Trace-Id": "qa-trace-abc123"})
        resp.expect.ok().header("X-Trace-Id").eq("qa-trace-abc123")
        resp.expect.body("traceId").eq("qa-trace-abc123")
