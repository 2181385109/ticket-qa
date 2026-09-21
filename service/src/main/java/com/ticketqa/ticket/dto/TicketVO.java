package com.ticketqa.ticket.dto;

import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import com.ticketqa.domain.enums.TicketStatus;

import java.time.LocalDateTime;

/**
 * 对外返回的工单视图。和实体分开:实体有 deleted 这类内部字段,也不希望接口形状被表结构绑死。
 */
public record TicketVO(
        Long id,
        String ticketNo,
        String title,
        String content,
        TicketCategory category,
        TicketPriority priority,
        TicketStatus status,
        Long customerId,
        Long groupId,
        Long assigneeId,
        LocalDateTime slaDeadline,
        LocalDateTime escalatedAt,
        LocalDateTime closedAt,
        /** 乐观锁版本(ADR-016):每次成功写入 +1,客户端可据此判断自己读到的快照是否已过期 */
        Integer version,
        LocalDateTime createdAt,
        LocalDateTime updatedAt) {
}
