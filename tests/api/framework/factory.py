"""
测试数据工厂:造数 + 用例级清理。

- 每个用例拿一个 TicketFactory(function 级 fixture),它记住自己造过的所有工单 id,
  用例结束(不管成功失败)按 id 硬删相关五张表——用例之间不共享、不污染、可重复执行。
- 造数走真实接口(POST /api/tickets → grab → transit ...),不是直接 INSERT:
  这样造出来的数据带审计、带 LLM 记录、带 MQ 消息,和线上数据同构;
  只有"把截止时间拨到过去 / 把关闭时间拨到 8 天前"这种时间旅行才直接改库。
- 标题带一个 8 位随机 token,只用 a-f 字母:既保证唯一,又保证不会意外命中
  关键词规则里的 "404" / "500"(数字会进 TECH 规则)和挡板正则里的 error/login。
"""
from __future__ import annotations

import random
from typing import Any

import allure

from .client import ApiClient
from .db import Db
from .users import User, Users

CATEGORIES = ("BILLING", "TECH", "REFUND", "OTHER")
PRIORITIES = ("P0", "P1", "P2")
STATUSES = ("PENDING", "ASSIGNED", "PROCESSING", "WAIT_CONFIRM", "CLOSED", "ESCALATED")


def token(n: int = 8) -> str:
    return "".join(random.choices("abcdef", k=n))


class TicketFactory:
    def __init__(self, api: ApiClient, db: Db):
        self.api = api                     # 已经是 ADMIN 身份的客户端
        self.db = db
        self.created_ids: list[int] = []

    # ------------------------------------------------------------------ 基础

    def title(self, base: str = "自动化工单") -> str:
        return f"{base} {token()}"

    def create(self, title: str | None = None, content: str = "自动化用例造数", customer_id: int | None = None,
               group_id: int | None = None, as_user: User = Users.ADMIN, **extra) -> dict[str, Any]:
        title = title or self.title()
        with allure.step(f"造数:创建工单「{title}」group={group_id or 1}"):
            resp = self.api.as_user(as_user).create_ticket(title, content, customer_id or random.randint(1000, 9999),
                                                           group_id, **extra)
            resp.expect.created()
            data = resp.data
            self.created_ids.append(int(data["id"]))
            return data

    def track(self, ticket_id: int) -> None:
        """用例自己通过接口创建的工单也登记进来,一并清理"""
        if ticket_id not in self.created_ids:
            self.created_ids.append(int(ticket_id))

    # ------------------------------------------------------------------ 各状态

    def pending(self, group_id: int = 1, **kw) -> dict[str, Any]:
        return self.create(group_id=group_id, **kw)

    def assigned(self, agent: User = Users.AGENT_A, **kw) -> dict[str, Any]:
        t = self.create(group_id=agent.group_id, **kw)
        with allure.step(f"造数:{agent} 抢单 #{t['id']}"):
            resp = self.api.as_user(agent).grab(t["id"])
            resp.expect.ok().data("status").eq("ASSIGNED")
            return resp.data

    def processing(self, agent: User = Users.AGENT_A, **kw) -> dict[str, Any]:
        t = self.assigned(agent, **kw)
        return self._transit(agent, t["id"], "PROCESSING")

    def wait_confirm(self, agent: User = Users.AGENT_A, **kw) -> dict[str, Any]:
        t = self.processing(agent, **kw)
        return self._transit(agent, t["id"], "WAIT_CONFIRM")

    def closed(self, agent: User = Users.AGENT_A, **kw) -> dict[str, Any]:
        t = self.wait_confirm(agent, **kw)
        return self._transit(agent, t["id"], "CLOSED")

    def escalated(self, group_id: int = 1, **kw) -> dict[str, Any]:
        """创建 → 截止时间拨到过去 → ADMIN 触发一轮扫描 → ESCALATED"""
        t = self.create(group_id=group_id, **kw)
        with allure.step(f"造数:把 #{t['id']} 的 sla_deadline 拨到 1 秒前并扫描"):
            self.db.set_sla_deadline_now(t["id"], offset_seconds=-1)
            self.api.sla_scan().expect.ok()
            resp = self.api.get_ticket(t["id"])
            resp.expect.ok().data("status").eq("ESCALATED")
            return resp.data

    def in_status(self, status: str, agent: User = Users.AGENT_A) -> dict[str, Any]:
        """状态迁移法用:按名字造一张处于指定状态的工单"""
        builders = {
            "PENDING": lambda: self.pending(agent.group_id),
            "ASSIGNED": lambda: self.assigned(agent),
            "PROCESSING": lambda: self.processing(agent),
            "WAIT_CONFIRM": lambda: self.wait_confirm(agent),
            "CLOSED": lambda: self.closed(agent),
            "ESCALATED": lambda: self.escalated(agent.group_id),
        }
        return builders[status]()

    def _transit(self, user: User, ticket_id: int, target: str) -> dict[str, Any]:
        with allure.step(f"造数:{user} 把 #{ticket_id} 流转到 {target}"):
            resp = self.api.as_user(user).transit(ticket_id, target)
            resp.expect.ok().data("status").eq(target)
            return resp.data

    # ------------------------------------------------------------------ 清理

    def cleanup(self) -> None:
        if self.created_ids:
            with allure.step(f"清理:硬删 {len(self.created_ids)} 张工单及关联记录 {self.created_ids}"):
                self.db.hard_delete_tickets(self.created_ids)
                self.created_ids.clear()
