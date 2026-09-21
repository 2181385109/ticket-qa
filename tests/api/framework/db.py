"""
直连 MySQL 的旁路观测 + 造数 + 清理。

接口层面看不见的东西全在这里取证:
  - llm_call_log.degraded / degrade_reason / response_model / raw_category(LLM 路径的固定断言项)
  - mq_message_dedup(消费是否发生、重复是否被拦)
  - ticket.sla_deadline(把截止时间拨到过去,让 SLA 扫描命中)
  - ticket.closed_at(把关闭时间拨到 8 天前,测重开窗口)
清理用硬删而不是接口的 DELETE(那是逻辑删):用例结束后库里不留痕,下次跑还是干净的。
"""
from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any, Iterable

import pymysql
import pymysql.cursors

from .config import Config


class Db:
    def __init__(self, config: Config):
        self._dsn = config.mysql_dsn

    @contextlib.contextmanager
    def _conn(self):
        conn = pymysql.connect(**self._dsn, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
        try:
            yield conn
        finally:
            conn.close()

    def query(self, sql: str, params: Iterable[Any] | None = None) -> list[dict]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def one(self, sql: str, params: Iterable[Any] | None = None) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Iterable[Any] | None = None) -> Any:
        row = self.one(sql, params)
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> int:
        with self._conn() as conn, conn.cursor() as cur:
            return cur.execute(sql, params)

    # ------------------------------------------------------------------ 工单

    def ticket(self, ticket_id: int) -> dict | None:
        return self.one("SELECT * FROM ticket WHERE id = %s", (ticket_id,))

    def set_sla_deadline_now(self, ticket_id: int, offset_seconds: float = 0) -> None:
        """把截止时间设成数据库的 NOW(3) + offset;用 DB 时钟避免宿主与容器时钟不一致"""
        self.execute("UPDATE ticket SET sla_deadline = TIMESTAMPADD(MICROSECOND, %s, NOW(3)) WHERE id = %s",
                     (int(offset_seconds * 1_000_000), ticket_id))

    def set_sla_deadline(self, ticket_id: int, deadline: datetime) -> None:
        self.execute("UPDATE ticket SET sla_deadline = %s WHERE id = %s", (deadline, ticket_id))

    def set_closed_at_days_ago(self, ticket_id: int, days: float) -> None:
        self.execute("UPDATE ticket SET closed_at = TIMESTAMPADD(SECOND, %s, NOW(3)) WHERE id = %s",
                     (-int(days * 86400), ticket_id))

    def db_now(self) -> datetime:
        return self.scalar("SELECT NOW(3) AS now")

    def count_tickets(self) -> int:
        return int(self.scalar("SELECT COUNT(*) AS c FROM ticket"))

    # ------------------------------------------------------------------ LLM 调用记录

    def llm_calls(self, ticket_id: int, scene: str | None = None) -> list[dict]:
        sql = "SELECT * FROM llm_call_log WHERE ticket_id = %s"
        params: list[Any] = [ticket_id]
        if scene:
            sql += " AND scene = %s"
            params.append(scene)
        return self.query(sql + " ORDER BY id", params)

    def llm_call(self, ticket_id: int, scene: str = "CLASSIFY") -> dict:
        rows = self.llm_calls(ticket_id, scene)
        assert len(rows) >= 1, f"工单 {ticket_id} 没有 scene={scene} 的 llm_call_log 记录"
        return rows[-1]

    # ------------------------------------------------------------------ 审计 / MQ / 附件

    def audit_logs(self, ticket_id: int) -> list[dict]:
        return self.query("SELECT * FROM ticket_audit_log WHERE ticket_id = %s ORDER BY id", (ticket_id,))

    def dedup_rows(self, ticket_id: int) -> list[dict]:
        return self.query("SELECT * FROM mq_message_dedup WHERE ticket_id = %s ORDER BY id", (ticket_id,))

    def attachments(self, ticket_id: int) -> list[dict]:
        return self.query("SELECT * FROM ticket_attachment WHERE ticket_id = %s ORDER BY id", (ticket_id,))

    # ------------------------------------------------------------------ 清理

    def hard_delete_tickets(self, ticket_ids: Iterable[int]) -> None:
        ids = [int(i) for i in ticket_ids]
        if not ids:
            return
        marks = ",".join(["%s"] * len(ids))
        for table in ("ticket_attachment", "ticket_audit_log", "llm_call_log", "mq_message_dedup", "ticket"):
            self.execute(f"DELETE FROM {table} WHERE {'id' if table == 'ticket' else 'ticket_id'} IN ({marks})", ids)
