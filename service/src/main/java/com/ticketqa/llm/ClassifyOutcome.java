package com.ticketqa.llm;

import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;

/**
 * 分类调用的最终结果:一定在枚举内,一定有值。调用方(TicketService)不需要知道是 LLM 还是规则给的。
 */
public record ClassifyOutcome(
        TicketCategory category,
        TicketPriority priority,
        boolean degraded,
        DegradeReason degradeReason,
        String requestModel,
        String responseModel,
        long latencyMs,
        boolean contractViolated,
        String rawCategory,
        Long callLogId,
        /** 交叉校验冲突,已改用规则结果,待人工复核(ADR-024) */
        boolean needsReview,
        /** ReviewReason 逗号连接;不冲突为 null */
        String reviewReason) {

    /** 第一阶段的形状:没有复核信息(降级、测试桩) */
    public ClassifyOutcome(TicketCategory category, TicketPriority priority, boolean degraded, DegradeReason degradeReason,
                           String requestModel, String responseModel, long latencyMs, boolean contractViolated,
                           String rawCategory, Long callLogId) {
        this(category, priority, degraded, degradeReason, requestModel, responseModel, latencyMs, contractViolated,
                rawCategory, callLogId, false, null);
    }

    /** 写进创建工单那条审计日志的备注 */
    public String describe() {
        StringBuilder sb = new StringBuilder("自动分类 category=").append(category).append(" priority=").append(priority);
        if (degraded) {
            sb.append(" degraded=true reason=").append(degradeReason).append(" (关键词规则)");
        } else {
            sb.append(" model=").append(responseModel == null ? requestModel : responseModel);
        }
        if (contractViolated) {
            sb.append(" contractViolated=true raw=").append(rawCategory);
        }
        if (needsReview) {
            sb.append(" needsReview=true reason=").append(reviewReason).append(" (采用规则结果)");
        }
        return sb.append(" latencyMs=").append(latencyMs).toString();
    }
}
