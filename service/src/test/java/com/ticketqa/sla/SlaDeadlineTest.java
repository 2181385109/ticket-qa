package com.ticketqa.sla;

import com.ticketqa.agent.AgentService;
import com.ticketqa.audit.AuditLogService;
import com.ticketqa.auth.AccessChecker;
import com.ticketqa.auth.UserContext;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import com.ticketqa.llm.ClassifyOutcome;
import com.ticketqa.llm.LlmCallLogService;
import com.ticketqa.llm.LlmService;
import com.ticketqa.mapper.TicketMapper;
import com.ticketqa.statemachine.TicketStateMachine;
import com.ticketqa.statemachine.TransitionTable;
import com.ticketqa.support.TestFixtures;
import com.ticketqa.ticket.GrabLock;
import com.ticketqa.ticket.TicketNoGenerator;
import com.ticketqa.ticket.TicketService;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import com.ticketqa.ticket.dto.CreateTicketRequest;
import com.ticketqa.ticket.dto.TicketVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

/**
 * SLA 截止时间的计算——边界值分析(docs/test-design/02-SLA边界值分析.md)。
 *
 * 规格:sla_deadline = created_at + {P0:15, P1:60, P2:240} 分钟,计时起点是创建时刻。
 * 这里验证"起点"和"时长"两个量:
 *   - 起点必须是 Clock 给出的 now(不是 LLM 调用完之后的时刻——LLM 可能耗 3 秒)
 *   - 时长按优先级查表
 *   - 跨天:23:50 创建的 P0 单,截止在次日 00:05
 *   - 跨时区:同一瞬间在 Asia/Shanghai 和 UTC 下创建,墙钟时间差 8 小时,但截止 - 创建 都是 15 分钟
 *
 * "恰好等于时限即超时"是 SQL 里的 <=,由 SlaOverdueQueryH2Test 用真实 SQL 验证;这里只管把截止时间算对。
 */
@ExtendWith(MockitoExtension.class)
class SlaDeadlineTest {

    @Mock
    private TicketMapper ticketMapper;
    @Mock
    private AccessChecker access;
    @Mock
    private AuditLogService auditLogService;
    @Mock
    private AgentService agentService;
    @Mock
    private LlmService llmService;
    @Mock
    private LlmCallLogService llmCallLogService;
    @Mock
    private ApplicationEventPublisher events;
    @Mock
    private TransactionTemplate txTemplate;
    @Mock
    private GrabLock grabLock;

    @BeforeEach
    void setUp() {
        UserContext.set(TestFixtures.admin());
        // TransactionTemplate.execute(callback):直接执行回调,不开真事务
        when(txTemplate.execute(any())).thenAnswer(inv -> {
            TransactionCallback<?> cb = inv.getArgument(0);
            return cb.doInTransaction(null);
        });
        when(ticketMapper.insert(any(Ticket.class))).thenAnswer(inv -> {
            Ticket t = inv.getArgument(0);
            t.setId(100L);
            return 1;
        });
    }

    @AfterEach
    void tearDown() {
        UserContext.clear();
    }

    private TicketService serviceAt(Clock clock) {
        return new TicketService(ticketMapper, new TicketStateMachine(new TransitionTable(TestFixtures.appProperties())),
                access, auditLogService, agentService, llmService, llmCallLogService, events, txTemplate,
                TestFixtures.appProperties(), clock, grabLock, new TicketNoGenerator(), new SimpleMeterRegistry());
    }

    private void llmSays(TicketPriority priority) {
        when(llmService.classify(anyString(), anyString())).thenReturn(new ClassifyOutcome(
                TicketCategory.TECH, priority, false, null, "mock-classifier-v1", "mock-classifier-v1",
                5, false, "TECH", 1L));
    }

    private Ticket inserted() {
        ArgumentCaptor<Ticket> captor = ArgumentCaptor.forClass(Ticket.class);
        org.mockito.Mockito.verify(ticketMapper).insert(captor.capture());
        return captor.getValue();
    }

    @ParameterizedTest(name = "[{index}] {0} → 截止 = 创建 + {1} 分钟")
    @CsvSource({"P0, 15", "P1, 60", "P2, 240"})
    @DisplayName("三档优先级各自的时限")
    void deadlineByPriority(TicketPriority priority, int minutes) {
        llmSays(priority);
        TicketService service = serviceAt(TestFixtures.fixedClock());

        TicketVO vo = service.create(new CreateTicketRequest("登录报错", "崩溃", 1001L, null));

        assertThat(vo.priority()).isEqualTo(priority);
        assertThat(vo.createdAt()).isEqualTo(TestFixtures.NOW);
        assertThat(vo.slaDeadline()).isEqualTo(TestFixtures.NOW.plusMinutes(minutes));
        assertThat(Duration.between(vo.createdAt(), vo.slaDeadline())).isEqualTo(Duration.ofMinutes(minutes));
    }

    @Test
    @DisplayName("计时起点是进入方法时的 now,与 LLM 调用耗时无关(createdAt 与 slaDeadline 落库值一致)")
    void deadlineAnchoredOnCreationInstant() {
        llmSays(TicketPriority.P0);
        TicketService service = serviceAt(TestFixtures.fixedClock());

        service.create(new CreateTicketRequest("登录报错", "崩溃", 1001L, null));

        Ticket t = inserted();
        assertThat(t.getCreatedAt()).isEqualTo(TestFixtures.NOW);
        assertThat(t.getSlaDeadline()).isEqualTo(t.getCreatedAt().plusMinutes(15));
    }

    @Test
    @DisplayName("跨天:23:50 创建的 P0 单,截止在次日 00:05")
    void crossesMidnight() {
        llmSays(TicketPriority.P0);
        LocalDateTime lateNight = LocalDateTime.of(2026, 9, 20, 23, 50, 0);
        TicketService service = serviceAt(TestFixtures.fixedClock(lateNight));

        TicketVO vo = service.create(new CreateTicketRequest("登录报错", "崩溃", 1001L, null));

        assertThat(vo.slaDeadline()).isEqualTo(LocalDateTime.of(2026, 9, 21, 0, 5, 0));
        assertThat(vo.slaDeadline().toLocalDate()).isAfter(vo.createdAt().toLocalDate());
    }

    @Test
    @DisplayName("跨月 + 跨天:9 月 30 日 22:30 创建的 P2 单,截止在 10 月 1 日 02:30")
    void crossesMonthBoundary() {
        llmSays(TicketPriority.P2);
        TicketService service = serviceAt(TestFixtures.fixedClock(LocalDateTime.of(2026, 9, 30, 22, 30, 0)));

        TicketVO vo = service.create(new CreateTicketRequest("咨询", "x", 1001L, null));

        assertThat(vo.slaDeadline()).isEqualTo(LocalDateTime.of(2026, 10, 1, 2, 30, 0));
    }

    @Test
    @DisplayName("跨时区:同一瞬间,Asia/Shanghai 与 UTC 的墙钟差 8 小时,但截止 - 创建 都是 15 分钟")
    void sameInstantDifferentZones() {
        llmSays(TicketPriority.P0);
        Instant instant = Instant.parse("2026-09-20T16:00:00Z");   // 北京时间 9/21 00:00,UTC 9/20 16:00
        TicketService shanghai = serviceAt(TestFixtures.fixedClock(instant, ZoneId.of("Asia/Shanghai")));
        TicketService utc = serviceAt(TestFixtures.fixedClock(instant, ZoneOffset.UTC));

        TicketVO a = shanghai.create(new CreateTicketRequest("登录报错", "崩溃", 1001L, null));
        TicketVO b = utc.create(new CreateTicketRequest("登录报错", "崩溃", 1001L, null));

        assertThat(a.createdAt()).isEqualTo(LocalDateTime.of(2026, 9, 21, 0, 0, 0));
        assertThat(b.createdAt()).isEqualTo(LocalDateTime.of(2026, 9, 20, 16, 0, 0));
        assertThat(Duration.between(a.createdAt(), b.createdAt())).isEqualTo(Duration.ofHours(-8));
        assertThat(Duration.between(a.createdAt(), a.slaDeadline())).isEqualTo(Duration.ofMinutes(15));
        assertThat(Duration.between(b.createdAt(), b.slaDeadline())).isEqualTo(Duration.ofMinutes(15));
        // 两个时区算出的截止时刻是同一个物理瞬间
        assertThat(a.slaDeadline().atZone(ZoneId.of("Asia/Shanghai")).toInstant())
                .isEqualTo(b.slaDeadline().atZone(ZoneOffset.UTC).toInstant());
    }

    @Test
    @DisplayName("降级分类给出的优先级同样决定时限(规则说 P1 → 60 分钟)")
    void degradedPriorityStillDrivesDeadline() {
        when(llmService.classify(anyString(), anyString())).thenReturn(new ClassifyOutcome(
                TicketCategory.REFUND, TicketPriority.P1, true, DegradeReason.TIMEOUT, "mock-classifier-v1", null,
                3000, false, null, 1L));
        TicketService service = serviceAt(TestFixtures.fixedClock());

        TicketVO vo = service.create(new CreateTicketRequest("退款", "x", 1001L, null));

        assertThat(vo.slaDeadline()).isEqualTo(TestFixtures.NOW.plusMinutes(60));
    }
}
