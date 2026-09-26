package com.ticketqa.domain.enums;

/**
 * LLM 降级原因。每个原因是否计入熔断器的连续失败,由构造参数说了算(ADR-004、ADR-024)——
 * 判断写在枚举里而不是 LlmService 的 if 里:新增一个原因时编译器逼着你回答"它算不算故障"。
 *
 * 计入的标准只有一条:**这个原因能不能说明上游不健康**。攻击者能稳定诱导出来的原因,一律不计入,
 * 否则几张注入工单就能让全站 LLM 路径熔断 60 秒(把我们自己的防御变成拒绝服务的开关)。
 */
public enum DegradeReason {
    /** 超过 llm.timeout-ms 未返回 */
    TIMEOUT(true),
    /** 熔断器打开期间直接走规则,根本没发请求 */
    CIRCUIT_OPEN(false),
    /** 下游返回非 2xx 或网络错误 */
    UPSTREAM_ERROR(true),
    /** 返回了 2xx 但响应体里**一个完整的 JSON 对象都读不出来**(输出格式整体崩坏) */
    BAD_RESPONSE(true),
    /**
     * 草稿输出检查命中(越权承诺 / 系统提示词片段),换成模板草稿(ADR-024)。
     * 这是防御动作不是故障:**不计入熔断**——否则攻击者提交 5 张注入工单各取一次草稿,就能让全站 LLM 路径熔断 60 秒。
     */
    UNSAFE_OUTPUT(false),
    /**
     * 输出里读得出完整的 JSON 对象,但不是"恰好一个对象":对象前后夹带了文字、或者有多个对象(KI-022 的防御,ADR-024)。
     * 与 BAD_RESPONSE 分开是因为它**能被攻击者诱导**:第一阶段 D-004 让模型先复述提示词原文(里面带 JSON 模板)、最后才给答案。
     * 上游是健康的,只是这次回答不能用——和 UNSAFE_OUTPUT 同一个理由,**不计入熔断**。
     */
    MIXED_OUTPUT(false);

    private final boolean countsTowardCircuit;

    DegradeReason(boolean countsTowardCircuit) {
        this.countsTowardCircuit = countsTowardCircuit;
    }

    /** 这次降级是否计入熔断器的连续失败(CIRCUIT_OPEN 根本没发请求,问它没有意义,返回 false) */
    public boolean countsTowardCircuit() {
        return countsTowardCircuit;
    }
}
