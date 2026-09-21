package com.ticketqa.llm;

import com.ticketqa.domain.enums.DegradeReason;

public record DraftOutcome(
        String draft,
        boolean degraded,
        DegradeReason degradeReason,
        String requestModel,
        String responseModel,
        long latencyMs,
        Long callLogId) {
}
