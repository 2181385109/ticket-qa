package com.ticketqa.ticket.dto;

import com.ticketqa.domain.enums.DegradeReason;

/** 回复草稿。degraded=true 表示这段话来自模板而不是模型。 */
public record ReplyDraftVO(
        Long ticketId,
        String draft,
        boolean degraded,
        DegradeReason degradeReason,
        String requestModel,
        String responseModel,
        long latencyMs) {
}
