package com.ticketqa.sla;

import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.mapper.TicketMapper;
import com.ticketqa.support.H2SliceTest;
import com.ticketqa.support.TestFixtures;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.springframework.beans.factory.annotation.Autowired;

import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * SLA 超时判定——闭区间的边界值分析(ADR-006,docs/test-design/02)。
 *
 * "恰好等于时限即算超时"这句规格最终落在 TicketMapper.selectSlaOverdueIds 的 `sla_deadline <= #{now}` 上。
 * Mockito 测不到一个 SQL 里的 <= 和 <,所以这一组用真实 SQL 跑在内存 H2 上(ADR-013)。
 *
 * 边界点(以 deadline = D 为中心):
 *   now = D - 1s  → 未超时        now = D - 1ms → 未超时
 *   now = D       → 超时(闭区间)
 *   now = D + 1ms → 超时          now = D + 1s  → 超时
 * 再加跨天(D 在 23:59:59.999,now 在次日 00:00:00.000)和状态 / 已升级 / 已删除三个过滤条件。
 *
 * 每个测试方法默认在事务里跑、结束后回滚(@MybatisPlusTest 自带 @Transactional),所以用例之间互不污染。
 */
@H2SliceTest
class SlaOverdueQueryH2Test {

    private static final LocalDateTime D = TestFixtures.NOW.plusMinutes(15);   // 截止时刻

    @Autowired
    private TicketMapper ticketMapper;

    private Long insert(TicketStatus status, LocalDateTime deadline) {
        Ticket t = TestFixtures.ticket(null, status);
        t.setTicketNo("T-" + UUID.randomUUID().toString().substring(0, 8));
        t.setSlaDeadline(deadline);
        ticketMapper.insert(t);
        return t.getId();
    }

    private List<Long> overdueAt(LocalDateTime now) {
        return ticketMapper.selectSlaOverdueIds(now, 100);
    }

    @Nested
    @DisplayName("闭区间边界:sla_deadline <= now")
    class ClosedInterval {

        @Test
        @DisplayName("now = deadline:超时(闭区间的核心用例)")
        void exactlyAtDeadlineIsOverdue() {
            Long id = insert(TicketStatus.PENDING, D);
            assertThat(overdueAt(D)).contains(id);
        }

        @Test
        @DisplayName("now = deadline - 1ms:未超时")
        void oneMillisecondBeforeIsNotOverdue() {
            Long id = insert(TicketStatus.PENDING, D);
            assertThat(overdueAt(D.minusNanos(1_000_000))).doesNotContain(id);
        }

        @Test
        @DisplayName("now = deadline - 1s:未超时")
        void oneSecondBeforeIsNotOverdue() {
            Long id = insert(TicketStatus.PENDING, D);
            assertThat(overdueAt(D.minusSeconds(1))).doesNotContain(id);
        }

        @Test
        @DisplayName("now = deadline + 1ms:超时")
        void oneMillisecondAfterIsOverdue() {
            Long id = insert(TicketStatus.PENDING, D);
            assertThat(overdueAt(D.plusNanos(1_000_000))).contains(id);
        }

        @Test
        @DisplayName("now = deadline + 1s:超时")
        void oneSecondAfterIsOverdue() {
            Long id = insert(TicketStatus.PENDING, D);
            assertThat(overdueAt(D.plusSeconds(1))).contains(id);
        }

        @Test
        @DisplayName("跨天:deadline 23:59:59.999,now 次日 00:00:00.000 → 超时(日期比较不能只比日)")
        void crossesMidnight() {
            LocalDateTime deadline = LocalDateTime.of(2026, 9, 20, 23, 59, 59, 999_000_000);
            Long id = insert(TicketStatus.ASSIGNED, deadline);
            assertThat(overdueAt(LocalDateTime.of(2026, 9, 21, 0, 0, 0))).contains(id);
            assertThat(overdueAt(LocalDateTime.of(2026, 9, 20, 23, 59, 59, 998_000_000))).doesNotContain(id);
        }
    }

    @Nested
    @DisplayName("过滤条件:只有 PENDING / ASSIGNED、未升级过、未删除 的才算")
    class Filters {

        @ParameterizedTest(name = "[{index}] 状态 {0} 超时但不该被扫到")
        @EnumSource(value = TicketStatus.class, names = {"PROCESSING", "WAIT_CONFIRM", "CLOSED", "ESCALATED"})
        void respondedStatusesAreIgnored(TicketStatus status) {
            Long id = insert(status, D.minusHours(1));
            assertThat(overdueAt(D)).doesNotContain(id);
        }

        @ParameterizedTest(name = "[{index}] 状态 {0} 超时应被扫到")
        @EnumSource(value = TicketStatus.class, names = {"PENDING", "ASSIGNED"})
        void unrespondedStatusesAreScanned(TicketStatus status) {
            Long id = insert(status, D.minusHours(1));
            assertThat(overdueAt(D)).contains(id);
        }

        @Test
        @DisplayName("escalated_at 非空:即使又回到 ASSIGNED 也不再扫到(永不二次升级)")
        void alreadyEscalatedIsIgnored() {
            Long id = insert(TicketStatus.ASSIGNED, D.minusHours(1));
            Ticket t = ticketMapper.selectById(id);
            t.setEscalatedAt(D.minusMinutes(30));
            ticketMapper.updateById(t);
            assertThat(overdueAt(D)).doesNotContain(id);
        }

        @Test
        @DisplayName("逻辑删除的工单不扫")
        void deletedIsIgnored() {
            Long id = insert(TicketStatus.PENDING, D.minusHours(1));
            ticketMapper.deleteById(id);
            assertThat(overdueAt(D)).doesNotContain(id);
        }

        @Test
        @DisplayName("按 sla_deadline 升序、受 limit 约束:最早超时的先被处理")
        void orderedByDeadlineAndLimited() {
            Long late = insert(TicketStatus.PENDING, D.minusMinutes(1));
            Long earliest = insert(TicketStatus.PENDING, D.minusMinutes(30));
            Long middle = insert(TicketStatus.PENDING, D.minusMinutes(10));

            assertThat(ticketMapper.selectSlaOverdueIds(D, 2)).containsExactly(earliest, middle);
            assertThat(ticketMapper.selectSlaOverdueIds(D, 10)).containsExactly(earliest, middle, late);
        }
    }

    @Nested
    @DisplayName("条件更新:同一工单绝不会被升级两次")
    class ConditionalUpdate {

        @Test
        @DisplayName("第一次影响 1 行并写入 escalated_at;第二次 0 行")
        void escalatesOnceOnly() {
            Long id = insert(TicketStatus.PENDING, D);
            assertThat(escalate(id, D)).isEqualTo(1);
            Ticket after = ticketMapper.selectById(id);
            assertThat(after.getStatus()).isEqualTo(TicketStatus.ESCALATED);
            assertThat(after.getEscalatedAt()).isEqualTo(D);
            assertThat(after.getUpdatedAt()).isEqualTo(D);
            assertThat(after.getVersion()).as("条件更新也递增 version").isEqualTo(1);

            assertThat(escalate(id, D.plusMinutes(1))).isZero();
            assertThat(ticketMapper.selectById(id).getEscalatedAt()).as("首次升级时间不被覆盖").isEqualTo(D);
        }

        @Test
        @DisplayName("升级后被组长指派回 ASSIGNED,再扫:条件更新 0 行,escalated_at 仍在")
        void reassignedAfterEscalationIsNotEscalatedAgain() {
            Long id = insert(TicketStatus.PENDING, D);
            escalate(id, D);
            Ticket t = ticketMapper.selectById(id);
            t.setStatus(TicketStatus.ASSIGNED);
            t.setAssigneeId(3L);
            ticketMapper.updateById(t);

            assertThat(overdueAt(D.plusHours(1))).doesNotContain(id);
            assertThat(escalate(id, D.plusHours(1))).isZero();
            assertThat(ticketMapper.selectById(id).getStatus()).isEqualTo(TicketStatus.ASSIGNED);
        }

        @Test
        @DisplayName("人工恰好在扫描后、升级前把工单推进到 PROCESSING:条件更新 0 行,不会覆盖人工操作")
        void manualProgressWinsTheRace() {
            Long id = insert(TicketStatus.ASSIGNED, D);
            List<Long> scanned = overdueAt(D);
            assertThat(scanned).contains(id);

            Ticket t = ticketMapper.selectById(id);
            t.setStatus(TicketStatus.PROCESSING);
            ticketMapper.updateById(t);

            assertThat(escalate(id, D)).isZero();
            assertThat(ticketMapper.selectById(id).getStatus()).isEqualTo(TicketStatus.PROCESSING);
            assertThat(ticketMapper.selectById(id).getEscalatedAt()).isNull();
        }

        @Test
        @DisplayName("KI-009 的 SQL 级复现:扫描读到 PENDING,升级前被抢成 ASSIGNED——带 status/version 的条件更新影响 0 行,不会写出 PENDING→ESCALATED 的假审计")
        void staleFromStatusDoesNotEscalate() {
            Long id = insert(TicketStatus.PENDING, D);
            Ticket snapshot = ticketMapper.selectById(id);          // 调度器读到的快照:PENDING, version 0

            assertThat(ticketMapper.grabIfPending(id, 3L, snapshot.getVersion(), D)).isEqualTo(1);   // 坐席抢单先提交

            int affected = ticketMapper.escalateIfStillUnresponded(id, snapshot.getStatus().name(), snapshot.getVersion(), D);
            assertThat(affected).as("快照已过期,升级必须放弃,交给下一轮重新读").isZero();
            Ticket after = ticketMapper.selectById(id);
            assertThat(after.getStatus()).isEqualTo(TicketStatus.ASSIGNED);
            assertThat(after.getEscalatedAt()).isNull();

            // 下一轮重新读到 ASSIGNED / version 1,这次能升级,审计 from 就会是真实的 ASSIGNED
            assertThat(ticketMapper.escalateIfStillUnresponded(id, "ASSIGNED", after.getVersion(), D.plusSeconds(30))).isEqualTo(1);
        }
    }

    @Nested
    @DisplayName("抢单条件更新 grabIfPending(ADR-016):status='PENDING' AND version=? 写在 WHERE 里")
    class GrabConditionalUpdate {

        @Test
        @DisplayName("第一次影响 1 行:ASSIGNED、assignee、version+1;同一快照再来一次 0 行(status 已变,version 也已变)")
        void firstWinsRestLose() {
            Long id = insert(TicketStatus.PENDING, D);
            Ticket snapshot = ticketMapper.selectById(id);

            assertThat(ticketMapper.grabIfPending(id, 3L, snapshot.getVersion(), D)).isEqualTo(1);
            Ticket after = ticketMapper.selectById(id);
            assertThat(after.getStatus()).isEqualTo(TicketStatus.ASSIGNED);
            assertThat(after.getAssigneeId()).isEqualTo(3L);
            assertThat(after.getVersion()).isEqualTo(snapshot.getVersion() + 1);
            assertThat(after.getUpdatedAt()).isEqualTo(D);

            assertThat(ticketMapper.grabIfPending(id, 4L, snapshot.getVersion(), D)).as("同一份过期快照").isZero();
            assertThat(ticketMapper.grabIfPending(id, 4L, after.getVersion(), D)).as("版本对了但 status 不是 PENDING").isZero();
            assertThat(ticketMapper.selectById(id).getAssigneeId()).as("assignee 没被覆盖").isEqualTo(3L);
        }

        @Test
        @DisplayName("version 不匹配(标题被人改过)即使仍是 PENDING 也影响 0 行:快照过期就不能写")
        void staleVersionLoses() {
            Long id = insert(TicketStatus.PENDING, D);
            // 注意 MyBatis 一级缓存:同一 SqlSession(同一事务)里 selectById 两次返回同一个对象,
            // 所以"过期快照"要在别人写之前把 version 值拷出来,而不是再 select 一次
            Integer staleVersion = ticketMapper.selectById(id).getVersion();

            Ticket editor = ticketMapper.selectById(id);
            editor.setTitle("改过标题");
            assertThat(ticketMapper.updateById(editor)).isEqualTo(1);     // 乐观锁插件让 version 变成 1

            assertThat(ticketMapper.grabIfPending(id, 3L, staleVersion, D)).isZero();
            assertThat(ticketMapper.selectById(id).getStatus()).isEqualTo(TicketStatus.PENDING);
        }

        @Test
        @DisplayName("乐观锁插件:updateById 带旧 version 影响 0 行,带新 version 影响 1 行且 version 再 +1")
        void optimisticLockerRewritesUpdateById() {
            Long id = insert(TicketStatus.PENDING, D);
            Ticket a = ticketMapper.selectById(id);
            Ticket b = new Ticket();          // 另一个"客户端"手里的快照:同 id、同 version 0(不能再 select,见上一条的一级缓存说明)
            b.setId(id);
            b.setVersion(a.getVersion());

            a.setTitle("A 先写");
            assertThat(ticketMapper.updateById(a)).isEqualTo(1);
            assertThat(a.getVersion()).as("插件把新版本回填进实体").isEqualTo(1);

            b.setTitle("B 用过期快照写");
            assertThat(ticketMapper.updateById(b)).isZero();
            assertThat(ticketMapper.selectById(id).getTitle()).isEqualTo("A 先写");
        }
    }

    private int escalate(Long id, LocalDateTime now) {
        Ticket t = ticketMapper.selectById(id);
        return ticketMapper.escalateIfStillUnresponded(id, t.getStatus().name(), t.getVersion(), now);
    }
}
