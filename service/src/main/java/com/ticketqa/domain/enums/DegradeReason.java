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
    /** 返回了 2xx 但响应体解析不出来;分类输出不是恰好一个 JSON 对象也算(KI-022) */
    BAD_RESPONSE,
    /**
     * 草稿输出检查命中(越权承诺 / 系统提示词片段),换成模板草稿(ADR-024)。
     * 这是防御动作不是故障:**不计入熔断**——否则攻击者提交 5 张注入工单各取一次草稿,就能让全站 LLM 路径熔断 60 秒。
     */
    UNSAFE_OUTPUT
}
