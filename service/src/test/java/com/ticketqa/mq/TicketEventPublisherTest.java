package com.ticketqa.mq;

import com.ticketqa.config.RabbitConfig;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.mq.consumer.AssignedConsumer;
import com.ticketqa.mq.consumer.SlaEscalatedConsumer;
import com.ticketqa.mq.consumer.StatusChangedConsumer;
import com.ticketqa.mq.message.TicketEventMessage;
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
import org.springframework.amqp.AmqpConnectException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;

/**
 * 领域事件 → MQ 消息(ADR-002 的"提交后发送"那一侧)。
 *
 * 这里只测 publisher 自己的逻辑:路由键按事件类型、消息字段一一映射、messageId 每条唯一、
 * 发送失败只打点不抛(事务已提交,抛也救不回来)。
 * "AFTER_COMMIT 时机是否正确"属于事务语义,Mockito 测不到,由接口自动化里"状态变更后去重表出现记录"间接验证。
 *
 * 三个消费者也在这里顺带验证:各自用自己的 NAME 调用 consumeOnce(去重表按 consumer 区分)。
 */
@ExtendWith(MockitoExtension.class)
class TicketEventPublisherTest {

    @Mock
    private RabbitTemplate rabbitTemplate;
    @Mock
    private IdempotentConsumerSupport idempotent;

    private MeterRegistry registry;
    private TicketEventPublisher publisher;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        publisher = new TicketEventPublisher(rabbitTemplate, registry);
    }

    private static TicketDomainEvent event(EventType type) {
        return new TicketDomainEvent(type, 7L, "T20260920-ABCD1234", TicketStatus.PENDING, TicketStatus.ASSIGNED,
                3L, 2L, "一组组长", AuditSource.MANUAL, "trace-1", TestFixtures.NOW);
    }

    private double counter(String name) {
        return registry.find(name).counter() == null ? 0 : registry.find(name).counter().count();
    }

    @Test
    @DisplayName("按事件类型选路由键,消息字段逐一映射,messageId 是 UUID")
    void routesByEventTypeAndMapsFields() {
        publisher.onTicketEvent(event(EventType.ASSIGNED));

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(rabbitTemplate).convertAndSend(eq(RabbitConfig.EXCHANGE), eq("ticket.assigned"), captor.capture());
        TicketEventMessage m = (TicketEventMessage) captor.getValue();
        assertThat(m.getMessageId()).matches("[0-9a-f-]{36}");
        assertThat(m.getEventType()).isEqualTo(EventType.ASSIGNED);
        assertThat(m.getTicketId()).isEqualTo(7L);
        assertThat(m.getTicketNo()).isEqualTo("T20260920-ABCD1234");
        assertThat(m.getFromStatus()).isEqualTo(TicketStatus.PENDING);
        assertThat(m.getToStatus()).isEqualTo(TicketStatus.ASSIGNED);
        assertThat(m.getAssigneeId()).isEqualTo(3L);
        assertThat(m.getOperatorId()).isEqualTo(2L);
        assertThat(m.getOperatorName()).isEqualTo("一组组长");
        assertThat(m.getSource()).isEqualTo(AuditSource.MANUAL);
        assertThat(m.getTraceId()).isEqualTo("trace-1");
        assertThat(m.getOccurredAt()).isEqualTo(TestFixtures.NOW);
        assertThat(counter("mq_event_published_total")).isEqualTo(1);
    }

    @Test
    @DisplayName("三类事件各自的路由键")
    void routingKeys() {
        publisher.onTicketEvent(event(EventType.STATUS_CHANGED));
        publisher.onTicketEvent(event(EventType.SLA_ESCALATED));
        verify(rabbitTemplate).convertAndSend(eq(RabbitConfig.EXCHANGE), eq("ticket.status.changed"), any(Object.class));
        verify(rabbitTemplate).convertAndSend(eq(RabbitConfig.EXCHANGE), eq("ticket.sla.escalated"), any(Object.class));
    }

    @Test
    @DisplayName("同一个事件发两次,messageId 不同(去重靠的是生产端 id,不是内容)")
    void messageIdIsUniquePerSend() {
        TicketDomainEvent e = event(EventType.STATUS_CHANGED);
        publisher.onTicketEvent(e);
        publisher.onTicketEvent(e);
        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(rabbitTemplate, org.mockito.Mockito.times(2)).convertAndSend(anyString(), anyString(), captor.capture());
        String id1 = ((TicketEventMessage) captor.getAllValues().get(0)).getMessageId();
        String id2 = ((TicketEventMessage) captor.getAllValues().get(1)).getMessageId();
        assertThat(id1).isNotEqualTo(id2);
    }

    @Test
    @DisplayName("Broker 不可用:不抛异常(事务已提交),publish_failed+1,published 不变")
    void brokerDownIsCountedNotThrown() {
        doThrow(new AmqpConnectException(new RuntimeException("Connection refused")))
                .when(rabbitTemplate).convertAndSend(anyString(), anyString(), any(Object.class));

        assertThatCode(() -> publisher.onTicketEvent(event(EventType.STATUS_CHANGED))).doesNotThrowAnyException();

        assertThat(counter("mq_event_publish_failed_total")).isEqualTo(1);
        assertThat(counter("mq_event_published_total")).isZero();
    }

    @Test
    @DisplayName("三个消费者各自用固定的 consumer 名调用 consumeOnce")
    void consumersUseTheirOwnNames() {
        TicketEventMessage m = TicketEventMessage.from(event(EventType.STATUS_CHANGED));
        new StatusChangedConsumer(idempotent).onMessage(m);
        new AssignedConsumer(idempotent).onMessage(m);
        new SlaEscalatedConsumer(idempotent).onMessage(m);
        verify(idempotent).consumeOnce(eq("status-changed-notifier"), eq(m), any());
        verify(idempotent).consumeOnce(eq("assigned-notifier"), eq(m), any());
        verify(idempotent).consumeOnce(eq("sla-escalated-notifier"), eq(m), any());
    }
}
