package com.ticketqa.domain.enums;

/**
 * 工单状态。流转规则不在这里写,在 com.ticketqa.statemachine.TransitionTable(数据驱动)。
 */
public enum TicketStatus {
    PENDING,
    ASSIGNED,
    PROCESSING,
    WAIT_CONFIRM,
    CLOSED,
    ESCALATED
}
