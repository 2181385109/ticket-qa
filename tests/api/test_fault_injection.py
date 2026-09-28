"""
故障注入(docker compose stop / start)——问题清单第 10、11 条。

2026-09-20 的故障注入是手动做的(docs/findings/20260920-故障注入记录.md),这里把两个"没有用例约束"的结论变成用例:
  RabbitMQ 停机:任务书写"不丢、补投",ADR-002 明确放弃,实测 9 条永久丢失(KI-014)。
                 决定:选「丢失可观测」,不实现补投(ADR-018)。用例断言的就是可观测性:
                 publish_failed 计数增加、ERROR 日志有那一行、恢复后**没有**补投(去重表始终 0 行)。
  Redis 停机 / 恢复:停机时不 500、缓存 fail-open(日志可观测)、单次请求 ≤ 1500 ms、health 503;恢复后多久回到正常延迟——
                 (每请求通常 +1 s,但也可能立即失败回源,两条路径都合法,见 findings/20260928-测试缺陷-Redis停机用例把超时路径当成必然)
                 实测 23.6 s(Lettuce 重连退避,KI-015),用例给它一个 SLO(ADR-020:45 s)并把实测秒数记进 Allure。

排在整个会话最后(fault 标记):中间件停机期间跑其它用例毫无意义。需要 DOCKER_COMPOSE_CMD,没配就 skip。
"""
import time

import allure
import pytest

from framework.users import Users
from framework.waits import wait_until

pytestmark = [allure.feature("故障注入"), pytest.mark.fault, pytest.mark.slow, pytest.mark.db, pytest.mark.mq]


def _health_component(api, name: str) -> str | None:
    return api.health().path(f"components.{name}.status")


def _latency_ms(api, n: int = 3) -> float:
    return sum(api.me().elapsed_ms for _ in range(n)) / n


# fail-open 的观测点:服务没有缓存失败计数,CacheConfig.errorHandler 只打这一行 WARN(文件日志格式带 [traceId],KI-016)。
# err= 后面是 Spring 转换后的异常消息,Redis 不可达时只见过两种(findings/20260928-测试缺陷-Redis停机用例把超时路径当成必然):
#   "Redis command timed out" —— 断连期间命令进缓冲区,等满 spring.data.redis.timeout(500 ms);
#   "Redis exception"         —— Lettuce 在断连状态下收到过管道异常(如 Connection reset),记下 connectionError,之后命令立即失败。
_CACHE_GET_FAILED = "缓存读取失败,回源查库 cache=agents"
_FAIL_OPEN_ERRORS = {"err=Redis command timed out": "timed out", "err=Redis exception": "Redis exception"}


def _fail_open_path(line: str | None) -> str | None:
    if line is None:
        return None
    return next((name for marker, name in _FAIL_OPEN_ERRORS.items() if line.rstrip().endswith(marker)), line[-80:])


@allure.story("RabbitMQ 停机:丢失可观测,不补投(ADR-018)")
class TestRabbitOutage:

    def test_publish_failure_is_observable_and_not_replayed(self, api, tickets, db, metrics, faults, service_log, config):
        log_offset = service_log.size()
        before = metrics.snapshot()

        faults.stop("rabbitmq")
        try:
            wait_until(lambda: _health_component(api, "rabbit"), lambda s: s == "DOWN", timeout=60, interval=2, what="health rabbit=DOWN")

            with allure.step("停机期间:创建 + 抢单仍成功,事务已提交"):
                t = tickets.pending(group_id=1)
                api.as_user(Users.AGENT_A).grab(t["id"]).expect.ok()
                assert db.ticket(t["id"])["status"] == "ASSIGNED"
                assert len(db.audit_logs(t["id"])) == 2

            with allure.step("可观测 ①:mq_event_publish_failed_total 至少 +3(创建 1 条 + 抢单 2 条;后台 SLA 升级若恰好发生也会计入),published 不增"):
                failed = metrics.delta(before, "mq_event_publish_failed_total")
                assert failed >= 3, failed
                assert metrics.delta(before, "mq_event_published_total") == 0

            with allure.step("可观测 ②:ERROR 日志逐条写明 type / ticketId / messageId"):
                if service_log.available:
                    lines = service_log.lines_since(log_offset, "MQ 发送失败")
                    allure.attach("\n".join(lines), name="ERROR 日志", attachment_type=allure.attachment_type.TEXT)
                    mine = [ln for ln in lines if f"ticketId={t['id']}" in ln]
                    assert len(mine) == 3, f"应有 3 条本工单的 ERROR 行,实际 {len(mine)}"
                    assert all(" ERROR " in ln and "messageId=" in ln for ln in mine)
                else:
                    pytest.skip("SERVICE_LOG_PATH 不可用,跳过日志断言")
        finally:
            faults.start("rabbitmq")

        with allure.step("恢复:health rabbit=UP,新消息重新被消费(记录恢复用时)"):
            t0 = time.monotonic()
            wait_until(lambda: _health_component(api, "rabbit"), lambda s: s == "UP", timeout=90, interval=2, what="health rabbit=UP")
            probe = tickets.pending(group_id=1)
            wait_until(lambda: len(db.dedup_rows(probe["id"])), lambda n: n >= 1, timeout=config.rabbit_recovery_slo_seconds,
                       interval=1, what="恢复后新消息被消费")
            recovery = time.monotonic() - t0
            allure.attach(f"docker start 后 {recovery:.1f}s 恢复消费(SLO {config.rabbit_recovery_slo_seconds}s)",
                          name="RabbitMQ 恢复用时", attachment_type=allure.attachment_type.TEXT)

        with allure.step("不补投:停机期间的 3 条消息恢复 10 秒后仍然没有任何消费记录——这是登记在案的取舍,不是遗漏"):
            time.sleep(10)
            assert db.dedup_rows(t["id"]) == [], "出现了补投——ADR-018 的决定是不补投,若实现了 outbox 请同时改 ADR"
            assert metrics.delta(before, "mq_event_publish_failed_total") >= failed, "失败计数不回落(它是累计计数)"


@allure.story("Redis 停机与恢复时长(ADR-020)")
class TestRedisOutage:

    def test_fail_open_and_recovery_within_slo(self, api, tickets, db, metrics, faults, service_log, config):
        assert service_log.available, "SERVICE_LOG_PATH 不可用:fail-open 只能从服务日志观测(服务没有缓存失败计数)"
        baseline = _latency_ms(api)
        before = metrics.snapshot()
        log_offset = service_log.size()

        faults.stop("redis")
        try:
            wait_until(lambda: api.health().status, lambda s: s == 503, timeout=60, interval=2, what="health 503")
            assert _health_component(api, "redis") == "DOWN"

            with allure.step("停机期间:鉴权不 500、缓存 fail-open(每次读缓存失败都回源查库),每次 /me ≤ 1500 ms"):
                resps = [api.me() for _ in range(3)]
                assert [r.status for r in resps] == [200] * 3, [r.status for r in resps]
                fail_open = service_log.lines_since(log_offset, _CACHE_GET_FAILED)
                paths = [_fail_open_path(next((ln for ln in fail_open if f"[{r.trace_id}]" in ln), None)) for r in resps]
                degraded = sum(r.elapsed_ms for r in resps) / len(resps)
                allure.attach(
                    f"基线 {baseline:.0f}ms;停机期间 /me 逐次 {[r.elapsed_ms for r in resps]}ms\n"
                    f"本次路径:{paths}(timed out = 命令在断连缓冲里等满 500 ms 超时;"
                    f"Redis exception = Lettuce 已记下连接错误,命令立即失败)\n\n" + "\n".join(fail_open),
                    name="Redis 停机:fail-open 路径与耗时", attachment_type=allure.attachment_type.TEXT)
                assert None not in paths, f"有请求没有对应的'{_CACHE_GET_FAILED}'日志行(按 traceId 匹配):{paths}"
                assert set(paths) <= set(_FAIL_OPEN_ERRORS.values()), f"缓存失败原因不是 Redis 不可达的两种已知表现:{paths}"
                assert all(r.elapsed_ms <= 1500 for r in resps), \
                    f"单次 /me 超过 1500 ms(get + put 各 ≤ 500 ms 超时 + 余量),缓存操作可能没有受超时约束:{[r.elapsed_ms for r in resps]}"
                t = tickets.pending(group_id=1)
                api.as_user(Users.AGENT_A).grab(t["id"]).expect.ok()

            with allure.step("抢单前置锁 fail-open:grab_lock_unavailable_total +1,抢单仍成功(正确性靠条件 UPDATE)"):
                assert metrics.delta(before, "grab_lock_unavailable_total") == 1
                assert metrics.delta(before, "grab_lock_acquired_total") == 0

            with allure.step("SLA 扫描不加锁继续跑:手动扫描 200,sla_scan_lock_unavailable_total +1"):
                api.sla_scan().expect.ok()
                assert metrics.delta(before, "sla_scan_lock_unavailable_total") >= 1
        finally:
            faults.start("redis")

        with allure.step(f"恢复:health 回到 UP 且鉴权延迟回到 < 200 ms,用时 ≤ SLO {config.redis_recovery_slo_seconds}s"):
            t0 = time.monotonic()
            wait_until(lambda: (api.health().status, _latency_ms(api, 1)), lambda v: v[0] == 200 and v[1] < 200,
                       timeout=config.redis_recovery_slo_seconds, interval=1, what="health UP 且延迟恢复")
            recovery = time.monotonic() - t0
            allure.attach(f"基线 {baseline:.0f}ms → 停机 {degraded:.0f}ms → docker start 后 {recovery:.1f}s 恢复(SLO {config.redis_recovery_slo_seconds}s;2026-09-20 实测 23.6s)",
                          name="Redis 恢复用时", attachment_type=allure.attachment_type.TEXT)
            assert _latency_ms(api) < 200
