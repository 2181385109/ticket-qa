package com.ticketqa.llm;

import com.ticketqa.domain.enums.DegradeReason;

/**
 * LLM 客户端失败。reason 决定熔断器是否计数(ADR-004)。
 */
public class LlmException extends RuntimeException {

    private final DegradeReason reason;

    public LlmException(DegradeReason reason, String message, Throwable cause) {
        super(message, cause);
        this.reason = reason;
    }

    public LlmException(DegradeReason reason, String message) {
        this(reason, message, null);
    }

    public DegradeReason getReason() {
        return reason;
    }
}
