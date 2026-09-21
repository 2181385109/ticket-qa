package com.ticketqa.ticket;

import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.entity.TicketAuditLog;
import com.ticketqa.ticket.dto.AuditLogVO;
import com.ticketqa.ticket.dto.TicketVO;

/**
 * 实体 → 视图对象。手写而不是 MapStruct(ADR-010):15 行代码,一眼看清字段对应关系。
 */
public final class TicketConverter {

    private TicketConverter() {
    }

    public static TicketVO toVO(Ticket t) {
        return new TicketVO(t.getId(), t.getTicketNo(), t.getTitle(), t.getContent(), t.getCategory(),
                t.getPriority(), t.getStatus(), t.getCustomerId(), t.getGroupId(), t.getAssigneeId(),
                t.getSlaDeadline(), t.getEscalatedAt(), t.getClosedAt(), t.getVersion(), t.getCreatedAt(), t.getUpdatedAt());
    }

    public static AuditLogVO toVO(TicketAuditLog a) {
        return new AuditLogVO(a.getId(), a.getTicketId(), a.getFromStatus(), a.getToStatus(), a.getOperatorId(),
                a.getOperatorName(), a.getSource(), a.getRemark(), a.getTraceId(), a.getCreatedAt());
    }
}
