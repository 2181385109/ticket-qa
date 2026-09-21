package com.ticketqa.ticket.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

/**
 * 创建工单的请求体。校验规则全在注解上(CLAUDE.md §6),方法体里不写判空。
 * record 组件上的注解会同时作用到字段和访问器,Hibernate Validator 按字段校验。
 */
public record CreateTicketRequest(
        @NotBlank(message = "标题不能为空") @Size(max = 200, message = "标题最长 200 字") String title,
        @NotBlank(message = "内容不能为空") @Size(max = 5000, message = "内容最长 5000 字") String content,
        @NotNull(message = "customerId 不能为空") @Positive(message = "customerId 必须为正数") Long customerId,
        @Positive(message = "groupId 必须为正数") Long groupId) {

    public Long groupIdOrDefault() {
        return groupId == null ? 1L : groupId;
    }
}
