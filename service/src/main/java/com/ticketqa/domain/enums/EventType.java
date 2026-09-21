package com.ticketqa.domain.enums;

/** 走 RabbitMQ 的三类事件(CLAUDE.md §5.4),routing key 见 RabbitConfig。 */
public enum EventType {
    STATUS_CHANGED("ticket.status.changed"),
    SLA_ESCALATED("ticket.sla.escalated"),
    ASSIGNED("ticket.assigned");

    private final String routingKey;

    EventType(String routingKey) {
        this.routingKey = routingKey;
    }

    public String routingKey() {
        return routingKey;
    }
}
