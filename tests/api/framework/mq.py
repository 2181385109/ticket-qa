"""
RabbitMQ 管理 API:把一条"已经消费过"的消息原样再投一次,制造重复投递。

生产环境里重复投递来自 Broker 重连、消费者 ack 前崩溃;测试里没法可靠制造这些,
所以直接对交换机重发一条 messageId 相同的消息——对消费端来说和真实重投无法区分(ADR-003)。
消息头 __TypeId__ 必须给,Jackson2JsonMessageConverter 靠它反序列化成 TicketEventMessage。
"""
from __future__ import annotations

import json
from typing import Any

import requests

EXCHANGE = "ticket.events"
TYPE_ID = "com.ticketqa.mq.message.TicketEventMessage"
ROUTING_KEYS = {
    "STATUS_CHANGED": "ticket.status.changed",
    "SLA_ESCALATED": "ticket.sla.escalated",
    "ASSIGNED": "ticket.assigned",
}
QUEUES = {
    "STATUS_CHANGED": "q.ticket.status-changed",
    "SLA_ESCALATED": "q.ticket.sla-escalated",
    "ASSIGNED": "q.ticket.assigned",
}


class RabbitMgmt:
    def __init__(self, base_url: str, user: str, password: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.auth = (user, password)
        self.timeout = timeout

    def healthy(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/api/overview", auth=self.auth, timeout=3).ok
        except requests.RequestException:
            return False

    def publish(self, event_type: str, payload: dict[str, Any]) -> bool:
        body = {
            "properties": {"content_type": "application/json", "headers": {"__TypeId__": TYPE_ID}},
            "routing_key": ROUTING_KEYS[event_type],
            "payload": json.dumps(payload, ensure_ascii=False),
            "payload_encoding": "string",
        }
        r = requests.post(f"{self.base_url}/api/exchanges/%2F/{EXCHANGE}/publish", json=body, auth=self.auth,
                          timeout=self.timeout)
        r.raise_for_status()
        return bool(r.json().get("routed"))

    def queue_depth(self, event_type: str) -> int:
        r = requests.get(f"{self.base_url}/api/queues/%2F/{QUEUES[event_type]}", auth=self.auth, timeout=self.timeout)
        r.raise_for_status()
        return int(r.json().get("messages", 0))

    @staticmethod
    def message_from_dedup_row(row: dict[str, Any], ticket: dict[str, Any], from_status: str | None,
                               to_status: str) -> dict[str, Any]:
        """按去重表里的一行重建当初的消息体(messageId 相同即可,其余字段消费者只用来打日志)"""
        return {
            "messageId": row["message_id"],
            "eventType": row["event_type"],
            "ticketId": ticket["id"],
            "ticketNo": ticket["ticketNo"],
            "fromStatus": from_status,
            "toStatus": to_status,
            "assigneeId": ticket.get("assigneeId"),
            "operatorId": None,
            "operatorName": "replay",
            "source": "MANUAL",
            "traceId": "replay-" + row["message_id"][:8],
            "occurredAt": "2026-09-20 00:00:00",
        }
