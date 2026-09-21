"""
种子坐席(ops/mysql/init/02-seed.sql)。鉴权只认 X-User-Id,所以"切换用户"就是换一个数字。
把它们做成常量而不是魔法数字:用例里写 Users.AGENT_B 比写 4 可读,判定表也能直接对照。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    group_id: int

    def __str__(self) -> str:
        return f"{self.username}(#{self.id},{self.role},group{self.group_id})"


class Users:
    ADMIN = User(1, "admin", "ADMIN", 1)
    LEADER_1 = User(2, "leader_1", "LEADER", 1)
    AGENT_A = User(3, "agent_a", "AGENT", 1)
    AGENT_B = User(4, "agent_b", "AGENT", 1)
    LEADER_2 = User(5, "leader_2", "LEADER", 2)
    AGENT_C = User(6, "agent_c", "AGENT", 2)

    ALL = (ADMIN, LEADER_1, AGENT_A, AGENT_B, LEADER_2, AGENT_C)
    UNKNOWN_ID = 999      # 不存在的坐席
