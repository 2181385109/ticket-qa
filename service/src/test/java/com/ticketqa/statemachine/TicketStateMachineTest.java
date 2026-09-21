package com.ticketqa.statemachine;

import com.ticketqa.common.IllegalTransitionException;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.support.TestFixtures;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static com.ticketqa.domain.enums.TicketStatus.ASSIGNED;
import static com.ticketqa.domain.enums.TicketStatus.CLOSED;
import static com.ticketqa.domain.enums.TicketStatus.PENDING;
import static com.ticketqa.domain.enums.TicketStatus.PROCESSING;
import static com.ticketqa.domain.enums.TicketStatus.WAIT_CONFIRM;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 状态机执行器:守卫 + 进入动作。
 *
 * 重开窗口用边界值分析:闭区间 [closedAt, closedAt + 7d],
 * 取 7d 整点、7d - 1s、7d + 1s 三个点(docs/test-design/01)。
 */
class TicketStateMachineTest {

    private static final LocalDateTime NOW = TestFixtures.NOW;

    private TicketStateMachine machine;

    @BeforeEach
    void setUp() {
        machine = new TicketStateMachine(new TransitionTable(TestFixtures.appProperties()));
    }

    @Nested
    @DisplayName("重开守卫:CLOSED -> PROCESSING 限 7 天内(闭区间)")
    class ReopenGuard {

        private Ticket closedAt(LocalDateTime closedAt) {
            Ticket t = TestFixtures.ticket(1L, CLOSED);
            t.setClosedAt(closedAt);
            return t;
        }

        @Test
        @DisplayName("恰好 7 天:允许(闭区间上界)")
        void exactlySevenDaysAllowed() {
            Ticket t = closedAt(NOW.minusDays(7));
            assertThatCode(() -> machine.assertAllowed(t, PROCESSING, NOW)).doesNotThrowAnyException();
        }

        @Test
        @DisplayName("7 天差 1 秒:允许")
        void oneSecondInsideWindowAllowed() {
            Ticket t = closedAt(NOW.minusDays(7).plusSeconds(1));
            assertThatCode(() -> machine.assertAllowed(t, PROCESSING, NOW)).doesNotThrowAnyException();
        }

        @Test
        @DisplayName("7 天多 1 秒:拒绝,异常消息说明超窗")
        void oneSecondOutsideWindowRejected() {
            Ticket t = closedAt(NOW.minusDays(7).minusSeconds(1));
            assertThatThrownBy(() -> machine.assertAllowed(t, PROCESSING, NOW))
                    .isInstanceOf(IllegalTransitionException.class)
                    .hasMessageContaining("7 天");
        }

        @Test
        @DisplayName("7 天多 1 毫秒:拒绝(边界精度到 DATETIME(3))")
        void oneMillisecondOutsideWindowRejected() {
            Ticket t = closedAt(NOW.minusDays(7).minusNanos(1_000_000));
            assertThatThrownBy(() -> machine.assertAllowed(t, PROCESSING, NOW))
                    .isInstanceOf(IllegalTransitionException.class);
        }

        @Test
        @DisplayName("closedAt 为空:拒绝(数据不完整不能判断窗口)")
        void missingClosedAtRejected() {
            Ticket t = closedAt(null);
            assertThatThrownBy(() -> machine.assertAllowed(t, PROCESSING, NOW))
                    .isInstanceOf(IllegalTransitionException.class)
                    .hasMessageContaining("关闭时间");
        }

        @Test
        @DisplayName("刚关闭立刻重开:允许(闭区间下界)")
        void reopenImmediatelyAllowed() {
            Ticket t = closedAt(NOW);
            assertThatCode(() -> machine.assertAllowed(t, PROCESSING, NOW)).doesNotThrowAnyException();
        }
    }

    @Nested
    @DisplayName("进入动作:进入某状态时对工单的固定副作用")
    class EntryActions {

        @Test
        @DisplayName("退回 PENDING 清空 assignee")
        void enteringPendingClearsAssignee() {
            Ticket t = TestFixtures.ticket(1L, ASSIGNED, 1L, 3L);
            machine.transit(t, PENDING, NOW);
            assertThat(t.getAssigneeId()).isNull();
        }

        @Test
        @DisplayName("进入 CLOSED 记录 closedAt = now")
        void enteringClosedStampsClosedAt() {
            Ticket t = TestFixtures.ticket(1L, WAIT_CONFIRM, 1L, 3L);
            machine.transit(t, CLOSED, NOW);
            assertThat(t.getClosedAt()).isEqualTo(NOW);
        }

        @Test
        @DisplayName("重开(CLOSED -> PROCESSING)清空 closedAt")
        void reopenClearsClosedAt() {
            Ticket t = TestFixtures.ticket(1L, CLOSED, 1L, 3L);
            t.setClosedAt(NOW.minusDays(1));
            machine.transit(t, PROCESSING, NOW);
            assertThat(t.getClosedAt()).isNull();
            assertThat(t.getStatus()).isEqualTo(PROCESSING);
        }

        @Test
        @DisplayName("用户不认可(WAIT_CONFIRM -> PROCESSING)不碰 closedAt,不碰 assignee")
        void rejectFromWaitConfirmKeepsFields() {
            Ticket t = TestFixtures.ticket(1L, WAIT_CONFIRM, 1L, 3L);
            machine.transit(t, PROCESSING, NOW);
            assertThat(t.getClosedAt()).isNull();
            assertThat(t.getAssigneeId()).isEqualTo(3L);
        }

        @Test
        @DisplayName("进入 ASSIGNED 没有进入动作:assignee 由 Service 设置,状态机不越权")
        void enteringAssignedHasNoAction() {
            Ticket t = TestFixtures.ticket(1L, PENDING);
            t.setAssigneeId(3L);   // Service 先设好
            machine.transit(t, ASSIGNED, NOW);
            assertThat(t.getAssigneeId()).isEqualTo(3L);
        }

        @Test
        @DisplayName("transit 返回流转前状态,供审计日志写 from")
        void transitReturnsPreviousStatus() {
            Ticket t = TestFixtures.ticket(1L, ASSIGNED, 1L, 3L);
            TicketStatus from = machine.transit(t, PROCESSING, NOW);
            assertThat(from).isEqualTo(ASSIGNED);
            assertThat(t.getStatus()).isEqualTo(PROCESSING);
        }
    }

    @Test
    @DisplayName("完整合法路径:PENDING → ASSIGNED → PROCESSING → WAIT_CONFIRM → CLOSED → PROCESSING(重开)")
    void fullHappyPath() {
        Ticket t = TestFixtures.ticket(1L, PENDING);
        t.setAssigneeId(3L);
        machine.transit(t, ASSIGNED, NOW);
        machine.transit(t, PROCESSING, NOW.plusMinutes(1));
        machine.transit(t, WAIT_CONFIRM, NOW.plusMinutes(2));
        machine.transit(t, CLOSED, NOW.plusMinutes(3));
        assertThat(t.getClosedAt()).isEqualTo(NOW.plusMinutes(3));
        machine.transit(t, PROCESSING, NOW.plusDays(3));
        assertThat(t.getStatus()).isEqualTo(PROCESSING);
        assertThat(t.getClosedAt()).isNull();
    }
}
