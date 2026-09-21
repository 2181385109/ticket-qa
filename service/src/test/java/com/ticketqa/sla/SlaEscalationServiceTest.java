package com.ticketqa.sla;

import com.ticketqa.audit.AuditLogService;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.mapper.TicketMapper;
import com.ticketqa.support.TestFixtures;
import com.ticketqa.ticket.event.TicketDomainEvent;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.context.ApplicationEventPublisher;

import java.time.LocalDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 单张工单的升级动作(ADR-006):防重复靠条件 UPDATE 的受影响行数。
 *
 * 判定表:
 *   工单存在? | 条件更新影响行数 | 动作
 *   否         | -                 | 返回 false,什么都不做
 *   是         | 0                 | skipped+1,不写审计不发事件
 *   是         | 1                 | 审计(SCHEDULER)+ 两条事件(STATUS_CHANGED, SLA_ESCALATED)+ escalated+1
 */
@ExtendWith(MockitoExtension.class)
class SlaEscalationServiceTest {

    private static final LocalDateTime NOW = TestFixtures.NOW;

    @Mock
    private TicketMapper ticketMapper;
    @Mock
    private AuditLogService auditLogService;
    @Mock
    private ApplicationEventPublisher events;

    private MeterRegistry registry;
    private SlaEscalationService service;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        service = new SlaEscalationService(ticketMapper, auditLogService, events, registry);
    }

    private double counter(String name) {
        return registry.find(name).counter() == null ? 0 : registry.find(name).counter().count();
    }

    @Test
    @DisplayName("条件更新影响 1 行:审计 source=SCHEDULER、from=原状态,两条事件,escalated+1")
    void escalatesWhenConditionalUpdateHits() {
        Ticket t = TestFixtures.ticket(7L, TicketStatus.ASSIGNED, 1L, 3L);
        t.setSlaDeadline(NOW.minusMinutes(1));
        t.setVersion(2);
        when(ticketMapper.selectById(7L)).thenReturn(t);
        // 条件更新必须带上读到的状态和版本(ADR-017):升级前被人流转过的行影响 0 行
        when(ticketMapper.escalateIfStillUnresponded(7L, "ASSIGNED", 2, NOW)).thenReturn(1);

        boolean escalated = service.escalate(7L, NOW);

        assertThat(escalated).isTrue();
        verify(auditLogService).record(eq(7L), eq(TicketStatus.ASSIGNED), eq(TicketStatus.ESCALATED),
                isNull(), eq("SCHEDULER"), eq(AuditSource.SCHEDULER), anyString());

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(events, times(2)).publishEvent(captor.capture());
        assertThat(captor.getAllValues())
                .extracting(e -> ((TicketDomainEvent) e).type())
                .containsExactly(EventType.STATUS_CHANGED, EventType.SLA_ESCALATED);
        TicketDomainEvent first = (TicketDomainEvent) captor.getAllValues().get(0);
        assertThat(first.fromStatus()).isEqualTo(TicketStatus.ASSIGNED);
        assertThat(first.toStatus()).isEqualTo(TicketStatus.ESCALATED);
        assertThat(first.source()).isEqualTo(AuditSource.SCHEDULER);
        assertThat(first.operatorId()).isNull();
        assertThat(first.assigneeId()).isEqualTo(3L);
        assertThat(first.occurredAt()).isEqualTo(NOW);

        assertThat(counter("sla_escalated_total")).isEqualTo(1);
        assertThat(counter("sla_escalation_skipped_total")).isZero();
    }

    @Test
    @DisplayName("条件更新影响 0 行(已被处理):skipped+1,不写审计、不发事件——同一工单不会被升级两次")
    void skipsWhenConditionalUpdateMisses() {
        Ticket t = TestFixtures.ticket(7L, TicketStatus.PENDING);
        when(ticketMapper.selectById(7L)).thenReturn(t);
        when(ticketMapper.escalateIfStillUnresponded(eq(7L), eq("PENDING"), any(), eq(NOW))).thenReturn(0);

        boolean escalated = service.escalate(7L, NOW);

        assertThat(escalated).isFalse();
        verify(auditLogService, never()).record(anyLong(), any(), any(), any(), anyString(), any(), any());
        verify(events, never()).publishEvent(any(Object.class));
        assertThat(counter("sla_escalation_skipped_total")).isEqualTo(1);
        assertThat(counter("sla_escalated_total")).isZero();
    }

    @Test
    @DisplayName("同一工单连续调用两次:第二次条件更新必然 0 行,只升级一次")
    void secondCallOnSameTicketIsNoOp() {
        Ticket t = TestFixtures.ticket(7L, TicketStatus.PENDING);
        when(ticketMapper.selectById(7L)).thenReturn(t);
        when(ticketMapper.escalateIfStillUnresponded(eq(7L), eq("PENDING"), any(), eq(NOW))).thenReturn(1).thenReturn(0);

        assertThat(service.escalate(7L, NOW)).isTrue();
        assertThat(service.escalate(7L, NOW)).isFalse();

        verify(auditLogService, times(1)).record(anyLong(), any(), any(), any(), anyString(), any(), any());
        verify(events, times(2)).publishEvent(any(Object.class));
        assertThat(counter("sla_escalated_total")).isEqualTo(1);
        assertThat(counter("sla_escalation_skipped_total")).isEqualTo(1);
    }

    @Test
    @DisplayName("工单不存在(扫描后被物理删除):返回 false,不执行条件更新")
    void missingTicketReturnsFalse() {
        when(ticketMapper.selectById(404L)).thenReturn(null);

        assertThat(service.escalate(404L, NOW)).isFalse();

        verify(ticketMapper, never()).escalateIfStillUnresponded(anyLong(), any(), any(), any());
        verify(events, never()).publishEvent(any(Object.class));
    }
}
