package com.ticketqa.ticket.dto;

import com.ticketqa.domain.enums.TicketStatus;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

/**
 * 通用状态流转请求。target 是目标状态;流转到 ASSIGNED 时必须带 assigneeId(在 Service 里校验,
 * 因为"是否必须"取决于 target,Bean Validation 单字段注解表达不了跨字段条件)。
 */
public record TransitionRequest(
        @NotNull(message = "target 不能为空") TicketStatus target,
        @Positive(message = "assigneeId 必须为正数") Long assigneeId,
        @Size(max = 500, message = "备注最长 500 字") String remark) {
}
