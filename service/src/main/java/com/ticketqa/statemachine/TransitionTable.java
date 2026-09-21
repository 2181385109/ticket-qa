package com.ticketqa.statemachine;

import com.ticketqa.config.AppProperties;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.TicketStatus;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.EnumMap;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.function.BiConsumer;

import static com.ticketqa.domain.enums.TicketStatus.ASSIGNED;
import static com.ticketqa.domain.enums.TicketStatus.CLOSED;
import static com.ticketqa.domain.enums.TicketStatus.ESCALATED;
import static com.ticketqa.domain.enums.TicketStatus.PENDING;
import static com.ticketqa.domain.enums.TicketStatus.PROCESSING;
import static com.ticketqa.domain.enums.TicketStatus.WAIT_CONFIRM;

/**
 * 状态迁移表——整个状态机的唯一事实来源(ADR-001)。
 *
 * 三张表:
 *  1. EDGES   : from → 允许的 to 集合,直接对应 CLAUDE.md §5.1 那六行
 *  2. GUARDS  : 特定边上的附加条件(目前只有 CLOSED → PROCESSING 的 7 天重开窗口)
 *  3. ACTIONS : 进入某状态时对工单做的固定副作用(清 assignee、记 closedAt……)
 *
 * 新增一种流转 = 在表里加一行,不需要改任何 if-else。
 */
@Component
public class TransitionTable {

    private static final Map<TicketStatus, Set<TicketStatus>> EDGES;

    static {
        Map<TicketStatus, Set<TicketStatus>> edges = new EnumMap<>(TicketStatus.class);
        edges.put(PENDING,      EnumSet.of(ASSIGNED, ESCALATED));
        edges.put(ASSIGNED,     EnumSet.of(PROCESSING, PENDING, ESCALATED));
        edges.put(PROCESSING,   EnumSet.of(WAIT_CONFIRM, ESCALATED));
        edges.put(WAIT_CONFIRM, EnumSet.of(CLOSED, PROCESSING));
        edges.put(CLOSED,       EnumSet.of(PROCESSING));
        edges.put(ESCALATED,    EnumSet.of(ASSIGNED));
        EDGES = Collections.unmodifiableMap(edges);
    }

    private final Map<Transition, TransitionGuard> guards = new HashMap<>();
    private final Map<TicketStatus, BiConsumer<Ticket, LocalDateTime>> entryActions = new EnumMap<>(TicketStatus.class);

    public TransitionTable(AppProperties props) {
        int reopenDays = props.ticket().reopenWindowDays();

        // 重开限 7 天内,闭区间:closedAt + 7d >= now 允许(与 SLA 的闭区间约定保持一致,ADR-006)
        guards.put(new Transition(CLOSED, PROCESSING), (ticket, now) -> {
            LocalDateTime closedAt = ticket.getClosedAt();
            if (closedAt == null) {
                return Optional.of("工单缺少关闭时间,无法判断重开窗口");
            }
            if (closedAt.plusDays(reopenDays).isBefore(now)) {
                return Optional.of("已关闭超过 " + reopenDays + " 天,不能重开");
            }
            return Optional.empty();
        });

        entryActions.put(PENDING, (ticket, now) -> ticket.setAssigneeId(null));
        entryActions.put(CLOSED, (ticket, now) -> ticket.setClosedAt(now));
        entryActions.put(PROCESSING, (ticket, now) -> {
            if (ticket.getStatus() == CLOSED) {
                ticket.setClosedAt(null);
            }
        });
    }

    public Set<TicketStatus> allowedTargets(TicketStatus from) {
        return EDGES.getOrDefault(from, EnumSet.noneOf(TicketStatus.class));
    }

    public boolean hasEdge(TicketStatus from, TicketStatus to) {
        return allowedTargets(from).contains(to);
    }

    public Optional<TransitionGuard> guardOf(TicketStatus from, TicketStatus to) {
        return Optional.ofNullable(guards.get(new Transition(from, to)));
    }

    public Optional<BiConsumer<Ticket, LocalDateTime>> entryActionOf(TicketStatus to) {
        return Optional.ofNullable(entryActions.get(to));
    }

    /** 只读视图,给测试和文档用:可以据此打印完整迁移表 */
    public Map<TicketStatus, Set<TicketStatus>> edges() {
        return EDGES;
    }
}
