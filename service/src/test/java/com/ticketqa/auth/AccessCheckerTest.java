package com.ticketqa.auth;

import com.ticketqa.common.AccessDeniedException;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.Role;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.support.TestFixtures;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 授权规则——判定表(docs/test-design/04-权限判定表.md)。
 *
 * 条件:C1 角色(AGENT / LEADER / ADMIN)  C2 工单是否在本组  C3 工单是否分配给自己
 * 动作:读写放行 / 水平越权 40301 / 垂直越权 40302
 *
 * 判定表的每一行是一条用例;同组不同人、跨组同角色、跨组组长这些"看起来像能过"的格子才是安全用例的价值所在。
 * 40301 vs 40302 的区分是刻意的:安全测试要能说出"是身份不对还是角色不够"。
 */
class AccessCheckerTest {

    private final AccessChecker checker = new AccessChecker();

    /** 组 1 的工单,分配给 agent_a(id=3) */
    private static Ticket group1AssignedToA() {
        return TestFixtures.ticket(10L, TicketStatus.ASSIGNED, 1L, 3L);
    }

    /** 组 1 的 PENDING 单,没有 assignee */
    private static Ticket group1Pending() {
        return TestFixtures.ticket(11L, TicketStatus.PENDING, 1L, null);
    }

    /** 组 2 的工单,分配给 agent_c(id=6) */
    private static Ticket group2AssignedToC() {
        return TestFixtures.ticket(20L, TicketStatus.ASSIGNED, 2L, 6L);
    }

    // ------------------------------------------------------------------ 读 / 写(同一套规则)

    static Stream<Arguments> readWriteTable() {
        return Stream.of(
                // 用户,                    工单,                    期望(null=放行,否则错误码)
                Arguments.of("agent_a 读自己的单",        TestFixtures.agentA(),  group1AssignedToA(),  null),
                Arguments.of("agent_b 读同组别人的单",     TestFixtures.agentB(),  group1AssignedToA(),  ErrorCode.FORBIDDEN),
                Arguments.of("agent_a 读同组 PENDING 单", TestFixtures.agentA(),  group1Pending(),      ErrorCode.FORBIDDEN),
                Arguments.of("agent_c 读跨组的单",        TestFixtures.agentC(),  group1AssignedToA(),  ErrorCode.FORBIDDEN),
                Arguments.of("leader_1 读本组任意单",     TestFixtures.leader1(), group1AssignedToA(),  null),
                Arguments.of("leader_1 读本组 PENDING 单", TestFixtures.leader1(), group1Pending(),     null),
                Arguments.of("leader_2 读跨组的单",       TestFixtures.leader2(), group1AssignedToA(),  ErrorCode.FORBIDDEN),
                Arguments.of("admin 读任意组的单",        TestFixtures.admin(),   group2AssignedToC(),  null)
        );
    }

    @ParameterizedTest(name = "[{index}] {0}")
    @MethodSource("readWriteTable")
    @DisplayName("checkRead 判定表")
    void readTable(String label, CurrentUser user, Ticket ticket, ErrorCode expected) {
        assertOutcome(() -> checker.checkRead(user, ticket), expected);
    }

    @ParameterizedTest(name = "[{index}] {0}")
    @MethodSource("readWriteTable")
    @DisplayName("checkWrite 判定表(与读同一套规则)")
    void writeTable(String label, CurrentUser user, Ticket ticket, ErrorCode expected) {
        assertOutcome(() -> checker.checkWrite(user, ticket), expected);
    }

    // ------------------------------------------------------------------ 抢单

    static Stream<Arguments> grabTable() {
        return Stream.of(
                Arguments.of("agent_a 抢本组 PENDING 单",  TestFixtures.agentA(),  group1Pending(),      null),
                Arguments.of("agent_b 抢本组 PENDING 单",  TestFixtures.agentB(),  group1Pending(),      null),
                Arguments.of("agent_c 抢跨组的单",         TestFixtures.agentC(),  group1Pending(),      ErrorCode.FORBIDDEN),
                Arguments.of("leader_2 抢跨组的单",        TestFixtures.leader2(), group1Pending(),      ErrorCode.FORBIDDEN),
                Arguments.of("admin 抢任意组的单",         TestFixtures.admin(),   group1Pending(),      null)
        );
    }

    @ParameterizedTest(name = "[{index}] {0}")
    @MethodSource("grabTable")
    @DisplayName("checkGrab 判定表:同组即可,不看 assignee")
    void grabTable(String label, CurrentUser user, Ticket ticket, ErrorCode expected) {
        assertOutcome(() -> checker.checkGrab(user, ticket), expected);
    }

    // ------------------------------------------------------------------ 改派(垂直越权点)

    static Stream<Arguments> assignTable() {
        return Stream.of(
                Arguments.of("agent_a 改派自己的单(角色不够)",   TestFixtures.agentA(),  group1AssignedToA(),  ErrorCode.ROLE_FORBIDDEN),
                Arguments.of("agent_b 改派同组的单(角色不够)",   TestFixtures.agentB(),  group1AssignedToA(),  ErrorCode.ROLE_FORBIDDEN),
                Arguments.of("leader_1 改派本组的单",            TestFixtures.leader1(), group1AssignedToA(),  null),
                Arguments.of("leader_2 改派跨组的单(身份不对)",  TestFixtures.leader2(), group1AssignedToA(),  ErrorCode.FORBIDDEN),
                Arguments.of("admin 改派任意组的单",             TestFixtures.admin(),   group2AssignedToC(),  null)
        );
    }

    @ParameterizedTest(name = "[{index}] {0}")
    @MethodSource("assignTable")
    @DisplayName("checkAssign 判定表:先查角色(40302)再查组(40301)")
    void assignTable(String label, CurrentUser user, Ticket ticket, ErrorCode expected) {
        assertOutcome(() -> checker.checkAssign(user, ticket), expected);
    }

    // ------------------------------------------------------------------ requireRole

    @Nested
    @DisplayName("requireRole:纯角色检查")
    class RequireRole {

        @Test
        void adminPassesAdminOnly() {
            assertThatCode(() -> checker.requireRole(TestFixtures.admin(), Role.ADMIN)).doesNotThrowAnyException();
        }

        @Test
        void leaderFailsAdminOnlyWith40302() {
            assertThatThrownBy(() -> checker.requireRole(TestFixtures.leader1(), Role.ADMIN))
                    .isInstanceOf(AccessDeniedException.class)
                    .extracting(e -> ((AccessDeniedException) e).getErrorCode())
                    .isEqualTo(ErrorCode.ROLE_FORBIDDEN);
        }

        @Test
        void anyOfSeveralRolesPasses() {
            assertThatCode(() -> checker.requireRole(TestFixtures.leader1(), Role.LEADER, Role.ADMIN)).doesNotThrowAnyException();
            assertThatThrownBy(() -> checker.requireRole(TestFixtures.agentA(), Role.LEADER, Role.ADMIN))
                    .isInstanceOf(AccessDeniedException.class);
        }
    }

    private static void assertOutcome(Runnable action, ErrorCode expected) {
        if (expected == null) {
            assertThatCode(action::run).doesNotThrowAnyException();
        } else {
            assertThatThrownBy(action::run)
                    .isInstanceOf(AccessDeniedException.class)
                    .extracting(e -> ((AccessDeniedException) e).getErrorCode())
                    .isEqualTo(expected);
        }
    }
}
