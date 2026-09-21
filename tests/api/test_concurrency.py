"""
并发正确性——竞态回归门禁(docs/test-design/08)。

2026-09-20 压测证明抢单 2 线程即 100% 重复分配(KI-008),审计 from_status 是内存快照(KI-009)。
修复(ADR-016 条件 UPDATE + version + Redis 前置锁;ADR-017 审计 from 取写时刻)之后,这些用例是防止回归的门禁。

断言写法(KI-010 的教训):
  - "≥2 个 200 即失败",不断言 409 的具体个数——能同时进库的线程数取决于那一刻的连接池大小,
    修复后进库的请求数还取决于 Redis 锁,两者都不是被测逻辑;
  - 每条用例前用 warmed_pool 把 HikariCP 撑满,CI 和本地起点一致;
  - 库里的证据优先于 HTTP 层:审计 to_status='ASSIGNED' 恰 1 行 + 序列连续(第 k 行 to == 第 k+1 行 from)。
"""
import allure
import pytest

from framework.audit import assert_audit_chain, count_edges
from framework.concurrency import fire_concurrently, summarize, successes
from framework.users import Users

pytestmark = [allure.feature("并发正确性"), pytest.mark.concurrency, pytest.mark.db]

GRAB_LOSER_CODES = {40901, 40904}     # 40901 进库后条件更新 0 行 / 顺序读到非 PENDING;40904 被 Redis 前置锁挡在库外
CONFLICT_CODES = {40901, 40903, 40904}


def _grab(t_id):
    return lambda client, i: client.grab(t_id)


@allure.story("抢单")
class TestGrabRace:

    @pytest.mark.parametrize("threads", [2, 10], ids=["t2", "t10"])
    @allure.title("{threads} 个坐席同时抢同一张 PENDING 单:恰好 1 个 200,其余 409;审计 ASSIGNED 恰 1 行且序列连续")
    def test_only_one_wins(self, tickets, api, db, config, metrics, metrics_before, warmed_pool, threads):
        t = tickets.pending(group_id=1)
        users = [Users.AGENT_A if i % 2 == 0 else Users.AGENT_B for i in range(threads)]

        responses = fire_concurrently(config.base_url, users, _grab(t["id"]))

        counter = summarize(responses, f"{threads} 线程抢单")
        winners = successes(responses)
        assert len(winners) == 1, f"重复分配(KI-008 回归):{len(winners)} 个 200,分布 {dict(counter)}"
        for r in responses:
            if r is not winners[0]:
                assert r.status == 409 and r.code in GRAB_LOSER_CODES, f"失败方应为 409/{GRAB_LOSER_CODES}: {r.summary()}"

        # 库里的证据:终值 assignee == 唯一赢家;ASSIGNED 审计恰 1 行;序列首尾相接
        final = api.get_ticket(t["id"]).expect.ok().data("status").eq("ASSIGNED").resp.data
        assert final["assigneeId"] == winners[0].data["assigneeId"]
        rows = db.audit_logs(t["id"])
        assert count_edges(rows, "PENDING", "ASSIGNED") == 1, rows
        assert sum(1 for r in rows if r["to_status"] == "ASSIGNED") == 1, rows
        assert_audit_chain(rows, final_status="ASSIGNED")

        # 三层防线各自的计数:进库的(acquired)+ 被锁挡的(rejected)= 线程数;进库后条件更新 0 行的 ≤ acquired-1
        acquired = metrics.delta(metrics_before, "grab_lock_acquired_total")
        rejected = metrics.delta(metrics_before, "grab_lock_rejected_total")
        unavailable = metrics.delta(metrics_before, "grab_lock_unavailable_total")
        db_conflict = metrics.delta(metrics_before, "grab_conflict_total")
        allure.attach(f"lock_acquired={acquired} lock_rejected={rejected} lock_unavailable={unavailable} db_conflict={db_conflict}",
                      name="三层防线计数", attachment_type=allure.attachment_type.TEXT)
        assert acquired + rejected + unavailable == threads
        assert db_conflict <= max(acquired + unavailable - 1, 0)

    @allure.title("连续 5 轮 2 线程(压测时的最小复现档位,当时 5/5 复现):5 张单各恰 1 个 200")
    def test_five_rounds_of_two(self, tickets, api, db, config, warmed_pool):
        for round_no in range(1, 6):
            t = tickets.pending(group_id=1)
            responses = fire_concurrently(config.base_url, [Users.AGENT_A, Users.AGENT_B], _grab(t["id"]))
            summarize(responses, f"第 {round_no} 轮")
            assert len(successes(responses)) == 1, f"第 {round_no} 轮出现 {len(successes(responses))} 个 200"
            rows = db.audit_logs(t["id"])
            assert sum(1 for r in rows if r["to_status"] == "ASSIGNED") == 1
            assert_audit_chain(rows, final_status="ASSIGNED", what=f"第 {round_no} 轮审计")


@allure.story("指派与抢单撞车")
class TestAssignVsGrab:

    @allure.title("组长指派 + 坐席抢单同时到达(重复 5 轮):终值 assignee 与成功响应一致,审计里没有假的 PENDING→ASSIGNED,序列连续")
    def test_leader_assign_races_agent_grab(self, tickets, api, db, config, warmed_pool):
        """
        两种合法结局:
          A. 指派先提交 → 抢单读到 ASSIGNED 或条件更新 0 行 → 409;审计 1 条 PENDING→ASSIGNED(组长)
          B. 抢单先提交 → 指派若已读到旧快照 → version 冲突 40903;若在抢单提交后才读 → 合法改派 ASSIGNED→ASSIGNED
             → 审计 PENDING→ASSIGNED(坐席)+ ASSIGNED→ASSIGNED(组长),两条都是真的
        修复前的结局:两个 200、两条 PENDING→ASSIGNED、组长的指派被抢单覆盖且审计里看不出来(压测持锁演示)。
        """
        outcomes = []
        for round_no in range(1, 6):
            t = tickets.pending(group_id=1)

            def act(client, i, t_id=t["id"]):
                return client.assign(t_id, Users.AGENT_B.id, remark="组长指派") if i == 0 else client.grab(t_id)

            responses = fire_concurrently(config.base_url, [Users.LEADER_1, Users.AGENT_A], act)
            counter = summarize(responses, f"第 {round_no} 轮 指派 vs 抢单")
            ok = successes(responses)
            assert 1 <= len(ok) <= 2, dict(counter)
            for r in responses:
                if r not in ok:
                    assert r.status == 409 and r.code in CONFLICT_CODES, r.summary()

            rows = db.audit_logs(t["id"])
            final = db.ticket(t["id"])
            assert count_edges(rows, "PENDING", "ASSIGNED") == 1, "PENDING→ASSIGNED 只能真实发生一次"
            assert_audit_chain(rows, final_status="ASSIGNED", what=f"第 {round_no} 轮审计")
            # 终值 assignee 必须等于按 id 顺序最后一条 ASSIGNED 审计的操作对象——组长指派不会被静默覆盖
            last_assigned = [r for r in rows if r["to_status"] == "ASSIGNED"][-1]
            expected_assignee = Users.AGENT_B.id if last_assigned["operator_id"] == Users.LEADER_1.id else Users.AGENT_A.id
            assert final["assignee_id"] == expected_assignee, (final, rows)
            outcomes.append(f"第 {round_no} 轮: 200×{len(ok)} 终值 assignee={final['assignee_id']} 审计 {len(rows)} 行")
        allure.attach("\n".join(outcomes), name="五轮结局", attachment_type=allure.attachment_type.TEXT)


@allure.story("其它状态跃迁的并发")
class TestTransitionRace:

    @allure.title("ASSIGNED 上 PROCESSING 与 PENDING(退回)同时到达:恰好 1 个 200——两个目标互不可达,谁先提交另一方必然 409;终态等于赢家的 target,序列连续")
    def test_assigned_fork_is_exclusive(self, tickets, api, db, config, warmed_pool):
        """
        选这一对是因为它们互斥:PROCESSING 之后不能退回 PENDING,PENDING 之后不能直接 PROCESSING。
        输家三种可能:读到旧快照 → 乐观锁 40903;读到新状态 PROCESSING → 状态机 40901;
        读到新状态 PENDING(退回已清空 assignee)→ 坐席不再拥有这张单 → 越权 40301。三种都对,不断言是哪一种。
        """
        t = tickets.assigned(Users.AGENT_A)

        def act(client, i, t_id=t["id"]):
            return client.transit(t_id, "PROCESSING" if i == 0 else "PENDING")

        responses = fire_concurrently(config.base_url, [Users.AGENT_A, Users.AGENT_A], act)
        summarize(responses, "PROCESSING vs PENDING")
        ok = successes(responses)
        assert len(ok) == 1, "互斥的两个目标只能成功一个"
        loser = [r for r in responses if r not in ok][0]
        assert (loser.status, loser.code) in {(409, 40901), (409, 40903), (403, 40301)}, loser.summary()

        final = db.ticket(t["id"])
        assert final["status"] == ok[0].data["status"]
        rows = db.audit_logs(t["id"])
        assert_audit_chain(rows, final_status=final["status"])
        assert rows[-1]["from_status"] == "ASSIGNED" and rows[-1]["to_status"] == final["status"]

    @allure.title("WAIT_CONFIRM 上 CLOSED 与 PROCESSING 同时到达:两种合法结局(1 个 200,或 CLOSED 后合法重开 2 个 200),审计都必须连续、终态等于最后一次成功的 target")
    def test_wait_confirm_fork(self, tickets, api, db, config, warmed_pool):
        """
        这一对不互斥:CLOSED 之后 PROCESSING 是合法的重开(7 天内)。所以第二个请求若在第一个提交后才读,
        会合法地成功——两个 200 是对的,审计里是 WAIT_CONFIRM→CLOSED→PROCESSING。
        不合法的只有一种:两个都用同一份旧快照写成功(修复前的行为),那时审计会出现两条 from=WAIT_CONFIRM。
        """
        t = tickets.wait_confirm(Users.AGENT_A)

        def act(client, i, t_id=t["id"]):
            return client.transit(t_id, "CLOSED" if i == 0 else "PROCESSING")

        responses = fire_concurrently(config.base_url, [Users.AGENT_A, Users.AGENT_A], act)
        summarize(responses, "CLOSED vs PROCESSING")
        ok = successes(responses)
        assert 1 <= len(ok) <= 2
        for r in responses:
            if r not in ok:
                assert r.status == 409 and r.code in {40901, 40903}, r.summary()

        rows = db.audit_logs(t["id"])
        final = db.ticket(t["id"])
        assert count_edges(rows, "WAIT_CONFIRM", "CLOSED") + count_edges(rows, "WAIT_CONFIRM", "PROCESSING") == 1, \
            "从 WAIT_CONFIRM 出发的转换只能真实发生一次"
        assert_audit_chain(rows, final_status=final["status"])
        if len(ok) == 2:
            assert [(r["from_status"], r["to_status"]) for r in rows[-2:]] == [("WAIT_CONFIRM", "CLOSED"), ("CLOSED", "PROCESSING")]
            assert final["status"] == "PROCESSING"

    @allure.title("同一目标(ASSIGNED→PROCESSING)两个请求同时到达:1 个 200 + 1 个 40903,审计只有 1 条 ASSIGNED→PROCESSING")
    def test_same_target_twice(self, tickets, api, db, config, warmed_pool):
        t = tickets.assigned(Users.AGENT_A)
        responses = fire_concurrently(config.base_url, [Users.AGENT_A, Users.AGENT_A],
                                      lambda client, i, t_id=t["id"]: client.transit(t_id, "PROCESSING"))
        summarize(responses, "PROCESSING ×2")
        ok = successes(responses)
        assert len(ok) == 1
        rows = db.audit_logs(t["id"])
        assert count_edges(rows, "ASSIGNED", "PROCESSING") == 1
        assert_audit_chain(rows, final_status="PROCESSING")

    @allure.title("修改标题与流转同时到达:两者都带 version,最多一个成功;都成功时 version 恰好 +2(顺序执行)")
    def test_update_vs_transition(self, tickets, api, db, config, warmed_pool):
        t = tickets.assigned(Users.AGENT_A)
        before = db.ticket(t["id"])["version"]

        def act(client, i, t_id=t["id"]):
            return client.update_ticket(t_id, "并发改标题", "内容") if i == 0 else client.transit(t_id, "PROCESSING")

        responses = fire_concurrently(config.base_url, [Users.AGENT_A, Users.AGENT_A], act)
        summarize(responses, "update vs transit")
        ok = successes(responses)
        after = db.ticket(t["id"])
        assert after["version"] == before + len(ok), "version 的增量 == 成功写入的次数"
        for r in responses:
            if r not in ok:
                r.expect.error(409, 40903)
        assert_audit_chain(db.audit_logs(t["id"]), final_status=after["status"])
