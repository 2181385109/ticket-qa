package com.ticketqa.ticket.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record UpdateTicketRequest(
        @NotBlank(message = "标题不能为空") @Size(max = 200, message = "标题最长 200 字") String title,
        @NotBlank(message = "内容不能为空") @Size(max = 5000, message = "内容最长 5000 字") String content) {
}
