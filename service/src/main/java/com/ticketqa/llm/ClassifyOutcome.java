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
        Long callLogId) {

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
        return sb.append(" latencyMs=").append(latencyMs).toString();
    }
}
