package com.ticketqa.domain.enums;

/**
 * LLM 输出没有被原样采用的原因(ADR-024)。落 llm_call_log.review_reason(多个用逗号连接),指标 llm_review_total{reason}。
 *
 * 分类场景的两个:交叉校验发现冲突 → 采用规则结果 + 标记人工复核(needs_review = 1)。
 * 草稿场景的两个:输出检查命中 → 换成模板草稿(degrade_reason = UNSAFE_OUTPUT),记下是哪条检查命中的;草稿不进复核,needs_review = 0。
 */
public enum ReviewReason {
    /** 模型 P0 且规则 P2(差两档) */
    PRIORITY_CONFLICT,
    /** 规则命中了至少一类关键词,模型给的类别不在命中集合里 */
    CATEGORY_CONFLICT,
    /** 草稿含越权承诺(退款 / 赔偿 / 办结时限 / 保证) */
    UNSAFE_PROMISE,
    /** 草稿含系统提示词片段 */
    UNSAFE_LEAK
}
