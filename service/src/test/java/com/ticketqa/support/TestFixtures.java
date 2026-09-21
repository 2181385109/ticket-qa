package com.ticketqa.support;

import com.ticketqa.auth.CurrentUser;
import com.ticketqa.config.AppProperties;
import com.ticketqa.config.LlmProperties;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.Role;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import com.ticketqa.domain.enums.TicketStatus;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;

/**
 * 单测共用的造数工具。每个方法返回一个全新对象,测试之间不共享可变状态。
 *
 * 与 application.yml 的默认值保持一致(15 / 60 / 240 分钟,7 天重开窗口,5MB,阈值 5 次 / 60 秒),
 * 这样单测里的边界值和接口自动化里的边界值指向同一组数字。
 */
public final class TestFixtures {

    public static final ZoneId SHANGHAI = ZoneId.of("Asia/Shanghai");

    /** 固定的"现在":2026-09-20 10:00:00(Asia/Shanghai)。边界值用例都从这个点出发。 */
    public static final LocalDateTime NOW = LocalDateTime.of(2026, 9, 20, 10, 0, 0);

    private TestFixtures() {
    }

    public static AppProperties appProperties() {
        return new AppProperties(
                SHANGHAI.getId(),
                new AppProperties.Sla(Map.of(TicketPriority.P0, 15, TicketPriority.P1, 60, TicketPriority.P2, 240),
                        30000, 100, 25),
                new AppProperties.Ticket(7, 3000),
                new AppProperties.Attachment("./target/test-attachments", 5L * 1024 * 1024,
                        List.of("jpg", "png", "pdf", "txt")));
    }

    public static LlmProperties llmProperties() {
        return new LlmProperties("mock", 3000,
                new LlmProperties.Circuit(5, 60),
                new LlmProperties.Real("https://api.example.com", "", "real-model"),
                new LlmProperties.Mock("http://localhost:8089", "mock-classifier-v1"));
    }

    /** Clock.fixed:LocalDateTime.now(clock) 永远返回同一个时刻,边界值才能精确到毫秒 */
    public static Clock fixedClock(LocalDateTime at) {
        return Clock.fixed(at.atZone(SHANGHAI).toInstant(), SHANGHAI);
    }

    public static Clock fixedClock() {
        return fixedClock(NOW);
    }

    /** 同一瞬间、不同时区的 Clock:跨时区用例用它验证"墙钟时间不同,但时长一致" */
    public static Clock fixedClock(Instant instant, ZoneId zone) {
        return Clock.fixed(instant, zone);
    }

    public static Ticket ticket(Long id, TicketStatus status) {
        Ticket t = new Ticket();
        t.setId(id);
        t.setTicketNo("T20260920-TEST" + id);
        t.setTitle("测试工单 " + id);
        t.setContent("内容");
        t.setCategory(TicketCategory.OTHER);
        t.setPriority(TicketPriority.P2);
        t.setStatus(status);
        t.setCustomerId(1001L);
        t.setGroupId(1L);
        t.setCreatedAt(NOW);
        t.setUpdatedAt(NOW);
        t.setSlaDeadline(NOW.plusMinutes(240));
        return t;
    }

    public static Ticket ticket(Long id, TicketStatus status, Long groupId, Long assigneeId) {
        Ticket t = ticket(id, status);
        t.setGroupId(groupId);
        t.setAssigneeId(assigneeId);
        return t;
    }

    // ---- 种子坐席(与 ops/mysql/init/02-seed.sql 一致) ----

    public static CurrentUser admin() {
        return new CurrentUser(1L, "admin", "管理员", Role.ADMIN, 1L);
    }

    public static CurrentUser leader1() {
        return new CurrentUser(2L, "leader_1", "一组组长", Role.LEADER, 1L);
    }

    public static CurrentUser agentA() {
        return new CurrentUser(3L, "agent_a", "坐席A", Role.AGENT, 1L);
    }

    public static CurrentUser agentB() {
        return new CurrentUser(4L, "agent_b", "坐席B", Role.AGENT, 1L);
    }

    public static CurrentUser leader2() {
        return new CurrentUser(5L, "leader_2", "二组组长", Role.LEADER, 2L);
    }

    public static CurrentUser agentC() {
        return new CurrentUser(6L, "agent_c", "坐席C", Role.AGENT, 2L);
    }
}
