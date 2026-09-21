package com.ticketqa.ticket.dto;

import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.TicketStatus;

import java.time.LocalDateTime;

public record AuditLogVO(
        Long id,
        Long ticketId,
        TicketStatus fromStatus,
        TicketStatus toStatus,
        Long operatorId,
        String operatorName,
        AuditSource source,
        String remark,
        String traceId,
        LocalDateTime createdAt) {
}
