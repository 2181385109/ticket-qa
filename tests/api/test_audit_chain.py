"""
审计序列连续性——KI-009 的反向断言(docs/test-design/08 §2)。

正向断言(test_state_machine / test_grab_assign 里"最后一行 from/to 是什么")在修复前的脏数据上也能通过,
因为每一行单看都合法。这里断言的是行与行之间的关系:首尾相接、终态一致、每条边在迁移表里。
对应 ADR-017:from_status 只在 UPDATE 命中 1 行之后写,所以它就是写之前那一行的真实状态。

用 SQL 直查而不是 /audit-logs 接口:接口返回的是 VO,这条断言是数据一致性校验(CLAUDE.md §5.8),要看表本身。
"""
import allure
import pytest

from framework.audit import assert_audit_chain, chain_violations
from framework.users import Users

pytestmark = [allure.feature("审计"), allure.story("序列连续性"), pytest.mark.db]


class TestAuditChain:

    @allure.title("完整生命周期 创建→抢单→处理→待确认→关闭→重开:7 行首尾相接,终态 PROCESSING")
    def test_full_lifecycle_chain(self, tickets, api, db):
        t = tickets.closed(Users.AGENT_A)
        api.as_user(Users.AGENT_A).transit(t["id"], "PROCESSING", remark="重开").expect.ok()

        rows = db.audit_logs(t["id"])
        assert [(r["from_status"], r["to_status"]) for r in rows] == [
            (None, "PENDING"), ("PENDING", "ASSIGNED"), ("ASSIGNED", "PROCESSING"),
            ("PROCESSING", "WAIT_CONFIRM"), ("WAIT_CONFIRM", "CLOSED"), ("CLOSED", "PROCESSING"),
        ]
        assert_audit_chain(rows, final_status="PROCESSING")

    @allure.title("退回 + 再抢 + 改派 + 升级 + 重新指派:含 ASSIGNED→ASSIGNED 改派边,仍然连续")
    def test_branchy_path_chain(self, tickets, api, db):
        t = tickets.assigned(Users.AGENT_A)
        api.as_user(Users.AGENT_A).transit(t["id"], "PENDING", remark="退回").expect.ok()
        api.as_user(Users.AGENT_B).grab(t["id"]).expect.ok()
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_A.id).expect.ok()
        db.set_sla_deadline_now(t["id"], offset_seconds=-1)
        api.sla_scan().expect.ok()
        api.as_user(Users.LEADER_1).assign(t["id"], Users.AGENT_B.id).expect.ok()

        rows = db.audit_logs(t["id"])
        assert [(r["from_status"], r["to_status"]) for r in rows] == [
            (None, "PENDING"), ("PENDING", "ASSIGNED"), ("ASSIGNED", "PENDING"), ("PENDING", "ASSIGNED"),
            ("ASSIGNED", "ASSIGNED"), ("ASSIGNED", "ESCALATED"), ("ESCALATED", "ASSIGNED"),
        ]
        assert_audit_chain(rows, final_status="ASSIGNED")
        assert rows[5]["source"] == "SCHEDULER" and rows[5]["from_status"] == "ASSIGNED", "升级审计的 from 是升级那一刻的真实状态"

    @allure.title("被拒绝的操作不留审计:非法流转 409 / 越权 403 / 已被抢 409 之后序列长度不变")
    def test_rejections_leave_no_rows(self, tickets, api, db):
        t = tickets.assigned(Users.AGENT_A)
        n = len(db.audit_logs(t["id"]))
        api.as_user(Users.AGENT_A).transit(t["id"], "CLOSED").expect.error(409, 40901)
        api.as_user(Users.AGENT_B).transit(t["id"], "PROCESSING").expect.error(403, 40301)
        api.as_user(Users.AGENT_B).grab(t["id"]).expect.error(409, 40901)
        rows = db.audit_logs(t["id"])
        assert len(rows) == n
        assert_audit_chain(rows, final_status="ASSIGNED")

    @allure.title("全库扫描:当前库里没有任何工单的审计序列断裂(修复前压测留下的脏数据会在这里现形)")
    def test_no_broken_chain_in_database(self, tickets, db):
        """按 ticket 分组一次取全库审计;工单数可能上万(压测后),所以只取最近 2000 张。

        用例自己先造三张不同终态的工单再扫:每个用例都硬删自己造的数据,在干净环境(CI、刚 cold_start 的本地)
        跑到这里时库可能是空的,扫描不能因此变成 skip——空库上的"没有断裂"什么也没证明。
        """
        seeded = [tickets.pending()["id"], tickets.escalated()["id"], tickets.closed(Users.AGENT_A)["id"]]
        scanned = db.query("SELECT id, status FROM ticket ORDER BY id DESC LIMIT 2000")
        ids = [t["id"] for t in scanned]
        assert set(seeded) <= set(ids), "本用例造的工单必须在扫描范围内"
        marks = ",".join(["%s"] * len(ids))
        rows = db.query(f"SELECT * FROM ticket_audit_log WHERE ticket_id IN ({marks}) ORDER BY ticket_id, id", ids)
        by_ticket: dict[int, list[dict]] = {}
        for r in rows:
            by_ticket.setdefault(r["ticket_id"], []).append(r)
        broken = {}
        for t in scanned:
            problems = chain_violations(by_ticket.get(t["id"], []), t["status"])
            if problems:
                broken[t["id"]] = problems
        allure.attach(f"扫描 {len(scanned)} 张工单 / {len(rows)} 行审计,断裂 {len(broken)} 张\n"
                      + "\n".join(f"{k}: {v}" for k, v in list(broken.items())[:50]),
                      name="全库审计连续性", attachment_type=allure.attachment_type.TEXT)
        assert not broken, f"{len(broken)} 张工单审计序列断裂,例如 {list(broken.items())[:3]}"
