package com.ticketqa.statemachine;

import com.ticketqa.common.IllegalTransitionException;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.TicketStatus;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 状态机执行器:查表 → 跑守卫 → 改状态 → 跑进入动作。
 * 它只改内存里的 Ticket 对象,不碰数据库、不发事件——持久化和事件是 Service 的事(ADR-002)。
 */
@Component
public class TicketStateMachine {

    private final TransitionTable table;

    public TicketStateMachine(TransitionTable table) {
        this.table = table;
    }

    /** 只校验不执行。非法时抛 IllegalTransitionException。 */
    public void assertAllowed(Ticket ticket, TicketStatus target, LocalDateTime now) {
        TicketStatus from = ticket.getStatus();
        if (!table.hasEdge(from, target)) {
            throw new IllegalTransitionException(from, target);
        }
        table.guardOf(from, target)
                .flatMap(guard -> guard.check(ticket, now))
                .ifPresent(reason -> {
                    throw new IllegalTransitionException(from, target, from + " -> " + target + " 被拒绝: " + reason);
                });
    }

    /**
     * 校验并执行:返回流转前的状态,方便调用方写审计。
     * 进入动作在 setStatus 之前执行,所以动作里 ticket.getStatus() 看到的还是 from——
     * PROCESSING 的动作靠这一点区分"重开"和"用户不认可"。
     */
    public TicketStatus transit(Ticket ticket, TicketStatus target, LocalDateTime now) {
        assertAllowed(ticket, target, now);
        TicketStatus from = ticket.getStatus();
        table.entryActionOf(target).ifPresent(action -> action.accept(ticket, now));
        ticket.setStatus(target);
        return from;
    }
}
