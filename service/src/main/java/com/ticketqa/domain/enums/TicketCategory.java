package com.ticketqa.domain.enums;

import java.util.Optional;

/**
 * 工单分类。LLM 返回的分类必须落在这个枚举里,越界一律归 OTHER(CLAUDE.md §5.5)。
 */
public enum TicketCategory {
    BILLING,
    TECH,
    REFUND,
    OTHER;

    /**
     * 宽松解析:大小写不敏感、去空白;解析不到返回 Optional.empty() 而不是抛异常,
     * 由调用方决定"越界"怎么处理(打点 + 落 OTHER)。
     */
    public static Optional<TicketCategory> parse(String raw) {
        if (raw == null) {
            return Optional.empty();
        }
        String normalized = raw.trim().toUpperCase();
        for (TicketCategory c : values()) {
            if (c.name().equals(normalized)) {
                return Optional.of(c);
            }
        }
        return Optional.empty();
    }
}
