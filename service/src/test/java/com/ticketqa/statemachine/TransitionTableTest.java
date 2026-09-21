package com.ticketqa.statemachine;

import com.ticketqa.common.IllegalTransitionException;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.support.TestFixtures;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.util.Arrays;
import java.util.EnumMap;
import java.util.EnumSet;
import java.util.Map;
import java.util.Set;
import java.util.stream.Stream;

import static com.ticketqa.domain.enums.TicketStatus.ASSIGNED;
import static com.ticketqa.domain.enums.TicketStatus.CLOSED;
import static com.ticketqa.domain.enums.TicketStatus.ESCALATED;
import static com.ticketqa.domain.enums.TicketStatus.PENDING;
import static com.ticketqa.domain.enums.TicketStatus.PROCESSING;
import static com.ticketqa.domain.enums.TicketStatus.WAIT_CONFIRM;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 状态迁移表——状态迁移法(docs/test-design/01-状态迁移表与状态机用例.md)。
 *
 * 6 个状态 × 6 个目标 = 36 格,每一格都是一条用例:11 格合法、25 格非法(含 6 个自环)。
 * 用例不是手挑的,是从"规格里的合法边集合"推导出来的:凡不在集合里的 (from, to) 都必须被拒绝。
 * 这样规格改一行(加一条边),SPEC 改一行,36 条用例自动跟着变——和 TransitionTable 的数据驱动是同一个思路。
 */
class TransitionTableTest {

    /** 规格(CLAUDE.md §5.1)的独立抄本:故意不引用 TransitionTable.EDGES,否则是拿实现测实现 */
    private static final Map<TicketStatus, Set<TicketStatus>> SPEC = new EnumMap<>(TicketStatus.class);

    static {
        SPEC.put(PENDING,      EnumSet.of(ASSIGNED, ESCALATED));
        SPEC.put(ASSIGNED,     EnumSet.of(PROCESSING, PENDING, ESCALATED));
        SPEC.put(PROCESSING,   EnumSet.of(WAIT_CONFIRM, ESCALATED));
        SPEC.put(WAIT_CONFIRM, EnumSet.of(CLOSED, PROCESSING));
        SPEC.put(CLOSED,       EnumSet.of(PROCESSING));
        SPEC.put(ESCALATED,    EnumSet.of(ASSIGNED));
    }

    private TransitionTable table;
    private TicketStateMachine machine;

    @BeforeEach
    void setUp() {
        table = new TransitionTable(TestFixtures.appProperties());
        machine = new TicketStateMachine(table);
    }

    @Test
    @DisplayName("迁移表与规格逐行一致:6 个起点、11 条边,不多不少")
    void edgesMatchSpecExactly() {
        assertThat(table.edges()).containsExactlyInAnyOrderEntriesOf(SPEC);
        long edgeCount = table.edges().values().stream().mapToLong(Set::size).sum();
        assertThat(edgeCount).isEqualTo(11);
    }

    /** 36 格全排列 */
    static Stream<Arguments> allCells() {
        return Arrays.stream(TicketStatus.values())
                .flatMap(from -> Arrays.stream(TicketStatus.values())
                        .map(to -> Arguments.of(from, to, SPEC.get(from).contains(to))));
    }

    @ParameterizedTest(name = "[{index}] {0} -> {1} 应为 {2}")
    @MethodSource("allCells")
    @DisplayName("36 格逐格:hasEdge 与规格一致")
    void everyCellMatchesSpec(TicketStatus from, TicketStatus to, boolean legal) {
        assertThat(table.hasEdge(from, to)).as("%s -> %s", from, to).isEqualTo(legal);
    }

    static Stream<Arguments> legalCells() {
        return allCells().filter(a -> (boolean) a.get()[2]);
    }

    static Stream<Arguments> illegalCells() {
        return allCells().filter(a -> !(boolean) a.get()[2]);
    }

    @ParameterizedTest(name = "[{index}] 合法 {0} -> {1}")
    @MethodSource("legalCells")
    @DisplayName("11 条合法边:状态机放行并改状态")
    void legalTransitionsPass(TicketStatus from, TicketStatus to, boolean legal) {
        Ticket ticket = TestFixtures.ticket(1L, from);
        if (from == CLOSED) {
            ticket.setClosedAt(TestFixtures.NOW.minusDays(1));   // 重开窗口内,守卫放行
        }
        assertThatCode(() -> machine.assertAllowed(ticket, to, TestFixtures.NOW)).doesNotThrowAnyException();
        TicketStatus returned = machine.transit(ticket, to, TestFixtures.NOW);
        assertThat(returned).isEqualTo(from);
        assertThat(ticket.getStatus()).isEqualTo(to);
    }

    @ParameterizedTest(name = "[{index}] 非法 {0} -> {1}")
    @MethodSource("illegalCells")
    @DisplayName("25 条非法边:抛 IllegalTransitionException,状态不变")
    void illegalTransitionsRejected(TicketStatus from, TicketStatus to, boolean legal) {
        Ticket ticket = TestFixtures.ticket(1L, from);
        ticket.setClosedAt(TestFixtures.NOW);   // 即使满足重开窗口,非法边也不该放行

        assertThatThrownBy(() -> machine.transit(ticket, to, TestFixtures.NOW))
                .isInstanceOf(IllegalTransitionException.class)
                .satisfies(e -> {
                    IllegalTransitionException ite = (IllegalTransitionException) e;
                    assertThat(ite.getFrom()).isEqualTo(from);
                    assertThat(ite.getTo()).isEqualTo(to);
                });
        assertThat(ticket.getStatus()).as("拒绝后状态必须保持不变").isEqualTo(from);
    }

    @Test
    @DisplayName("自环全部非法:同状态到同状态不是流转")
    void selfLoopsAreIllegal() {
        for (TicketStatus s : TicketStatus.values()) {
            assertThat(table.hasEdge(s, s)).as("%s -> %s", s, s).isFalse();
        }
    }

    @Test
    @DisplayName("每个状态都有出边,没有死状态;CLOSED 只能重开,ESCALATED 只能被指派")
    void noDeadStates() {
        for (TicketStatus s : TicketStatus.values()) {
            assertThat(table.allowedTargets(s)).as("%s 的出边", s).isNotEmpty();
        }
        assertThat(table.allowedTargets(CLOSED)).containsExactly(PROCESSING);
        assertThat(table.allowedTargets(ESCALATED)).containsExactly(ASSIGNED);
    }
}
