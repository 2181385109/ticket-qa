package com.ticketqa.statemachine;

import com.ticketqa.domain.enums.TicketStatus;

/**
 * 一条有向边 (from → to)。record 自动实现 equals/hashCode,所以能直接当 Map 的 key。
 */
public record Transition(TicketStatus from, TicketStatus to) {

    @Override
    public String toString() {
        return from + " -> " + to;
    }
}
