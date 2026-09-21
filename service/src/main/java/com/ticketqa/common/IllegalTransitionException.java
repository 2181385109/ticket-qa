package com.ticketqa.common;

import com.ticketqa.domain.enums.TicketStatus;

/**
 * 非法状态流转。CLAUDE.md §5.1 要求 Service 层拦截并抛出此异常。
 */
public class IllegalTransitionException extends BizException {

    private final TicketStatus from;
    private final TicketStatus to;

    public IllegalTransitionException(TicketStatus from, TicketStatus to) {
        this(from, to, "不允许从 " + from + " 流转到 " + to);
    }

    public IllegalTransitionException(TicketStatus from, TicketStatus to, String message) {
        super(ErrorCode.ILLEGAL_TRANSITION, message);
        this.from = from;
        this.to = to;
    }

    public TicketStatus getFrom() {
        return from;
    }

    public TicketStatus getTo() {
        return to;
    }
}
