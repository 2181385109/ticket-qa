package com.ticketqa.ticket.event;

import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.TicketStatus;

import java.time.LocalDateTime;

/**
 * 进程内领域事件。Service 在事务里 publish 它,TicketEventPublisher 在事务提交后才把它转成 MQ 消息(ADR-002)。
 * 用 Spring 自己的 ApplicationEvent 机制而不是直接调 RabbitTemplate,就是为了拿到"提交后"这个时机。
 */
public record TicketDomainEvent(
        EventType type,
        Long ticketId,
        String ticketNo,
        TicketStatus fromStatus,
        TicketStatus toStatus,
        Long assigneeId,
        Long operatorId,
        String operatorName,
        AuditSource source,
        String traceId,
        LocalDateTime occurredAt) {
}
