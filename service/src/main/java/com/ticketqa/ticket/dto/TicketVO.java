package com.ticketqa.ticket.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
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
        LocalDateTime updatedAt,
        /**
         * 只在建单响应里有值(ADR-024 交叉校验):true = 模型结果与规则冲突,已改用规则结果,建议人工复核。
         * 不落 ticket 表(复核标记的持久记录在 llm_call_log),所以详情 / 列表里没有这两个字段——NON_NULL 让它们不出现,而不是出现一个误导人的 null。
         */
        @JsonInclude(JsonInclude.Include.NON_NULL) Boolean needsReview,
        @JsonInclude(JsonInclude.Include.NON_NULL) String reviewReason) {
}
