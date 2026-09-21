package com.ticketqa.domain.enums;

/**
 * LLM 降级原因。哪些计入熔断器的连续失败见 ADR-004。
 */
public enum DegradeReason {
    /** 超过 llm.timeout-ms 未返回 */
    TIMEOUT,
    /** 熔断器打开期间直接走规则,根本没发请求 */
    CIRCUIT_OPEN,
    /** 下游返回非 2xx 或网络错误 */
    UPSTREAM_ERROR,
    /** 返回了 2xx 但响应体解析不出来 */
    BAD_RESPONSE
}
