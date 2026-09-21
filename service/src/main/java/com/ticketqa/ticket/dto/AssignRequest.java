package com.ticketqa.ticket.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

public record AssignRequest(
        @NotNull(message = "assigneeId 不能为空") @Positive(message = "assigneeId 必须为正数") Long assigneeId,
        @Size(max = 500, message = "备注最长 500 字") String remark) {
}
