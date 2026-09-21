"""
审计序列的反向断言(KI-009 的最便宜检查)。

正向断言只查"有没有那一行"(from=PENDING,to=ASSIGNED 存在),修复前的脏读数据完全能通过——
每一行单看都是合法迁移。反向断言查的是**行与行之间的关系**:

    1. 同一 ticket_id 的审计按 id 排序后,第 k 行 to_status == 第 k+1 行 from_status(首尾相接)
    2. 第一行 from_status 为空(创建),最后一行 to_status == ticket.status(终态一致)
    3. 每一条 (from, to) 都在状态迁移表里(或是 ASSIGNED→ASSIGNED 改派、NULL→PENDING 创建)

修复前并发抢过的单在这三条上必然失败(N 条 PENDING→ASSIGNED 里只有第一条的 from 是真的);
修复后(ADR-017:from 只在 UPDATE 命中 1 行后写)必然通过。
"""
from __future__ import annotations

import allure

# 与 service TransitionTable 一致(CLAUDE.md §5.1)+ 两条不走状态机的合法记录
LEGAL_EDGES: set[tuple[str | None, str]] = {
    (None, "PENDING"),                      # 创建
    ("PENDING", "ASSIGNED"), ("PENDING", "ESCALATED"),
    ("ASSIGNED", "PROCESSING"), ("ASSIGNED", "PENDING"), ("ASSIGNED", "ESCALATED"),
    ("ASSIGNED", "ASSIGNED"),               # 改派:只换人不换状态
    ("PROCESSING", "WAIT_CONFIRM"), ("PROCESSING", "ESCALATED"),
    ("WAIT_CONFIRM", "CLOSED"), ("WAIT_CONFIRM", "PROCESSING"),
    ("CLOSED", "PROCESSING"),
    ("ESCALATED", "ASSIGNED"),
}


def chain_violations(rows: list[dict], final_status: str | None = None) -> list[str]:
    """返回违反项的描述列表;空列表即序列连续。rows 是 ticket_audit_log 按 id 升序的行。"""
    problems: list[str] = []
    if not rows:
        return ["没有任何审计行"]
    if rows[0]["from_status"] is not None:
        problems.append(f"第一行 from 应为空(创建),实际 {rows[0]['from_status']} (id={rows[0]['id']})")
    for k in range(len(rows) - 1):
        a, b = rows[k], rows[k + 1]
        if a["to_status"] != b["from_status"]:
            problems.append(f"断裂: 第 {k + 1} 行 to={a['to_status']} (id={a['id']}) != 第 {k + 2} 行 from={b['from_status']} (id={b['id']})")
    for r in rows:
        if (r["from_status"], r["to_status"]) not in LEGAL_EDGES:
            problems.append(f"非法边: {r['from_status']} -> {r['to_status']} (id={r['id']})")
    if final_status is not None and rows[-1]["to_status"] != final_status:
        problems.append(f"终态不一致: 最后一行 to={rows[-1]['to_status']} (id={rows[-1]['id']}) != ticket.status={final_status}")
    return problems


def assert_audit_chain(rows: list[dict], final_status: str | None = None, what: str = "审计序列") -> None:
    rendered = "\n".join(f"#{r['id']} {r['from_status']} -> {r['to_status']} by {r['operator_id']} ({r['source']}) {r['remark']}" for r in rows)
    allure.attach(rendered or "(空)", name=f"{what}(按 id 升序)", attachment_type=allure.attachment_type.TEXT)
    problems = chain_violations(rows, final_status)
    with allure.step(f"{what}连续:第 k 行 to == 第 k+1 行 from,终态一致,每条边合法"):
        assert not problems, f"{what}不连续(KI-009):\n" + "\n".join(problems) + "\n\n" + rendered


def count_edges(rows: list[dict], from_status: str | None, to_status: str) -> int:
    return sum(1 for r in rows if r["from_status"] == from_status and r["to_status"] == to_status)
