package com.ticketqa.mq;

import com.ticketqa.domain.entity.MqMessageDedup;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.mapper.MqMessageDedupMapper;
import com.ticketqa.mq.message.TicketEventMessage;
import com.ticketqa.support.TestFixtures;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.MDC;
import org.springframework.dao.DuplicateKeyException;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 消费端幂等(ADR-003):同一条消息投递两次,业务只执行一次。
 *
 * 场景法:按"消息是否首次到达 / 业务是否成功"组合出四个场景。
 * 去重表的唯一键在这里用 Mockito 模拟——第二次 insert 抛 DuplicateKeyException;
 * 唯一键本身是否真的会冲突,由 MqMessageDedupH2Test 用真实 SQL 验证。
 */
@ExtendWith(MockitoExtension.class)
class IdempotentConsumerSupportTest {

    private static final String CONSUMER = "status-changed-notifier";

    @Mock
    private MqMessageDedupMapper dedupMapper;

    private MeterRegistry registry;
    private IdempotentConsumerSupport support;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        support = new IdempotentConsumerSupport(dedupMapper, TestFixtures.fixedClock(), registry);
    }

    private static TicketEventMessage message(String messageId) {
        TicketEventMessage m = new TicketEventMessage();
        m.setMessageId(messageId);
        m.setEventType(EventType.STATUS_CHANGED);
        m.setTicketId(7L);
        m.setTicketNo("T20260920-ABCD1234");
        m.setFromStatus(TicketStatus.PENDING);
        m.setToStatus(TicketStatus.ASSIGNED);
        m.setSource(AuditSource.MANUAL);
        m.setTraceId("trace-" + messageId);
        m.setOccurredAt(TestFixtures.NOW);
        return m;
    }

    /** 用"已见过的 (messageId, consumer)"集合模拟唯一键:第二次同样的组合抛 DuplicateKeyException */
    private void simulateUniqueKey() {
        Set<String> seen = new HashSet<>();
        when(dedupMapper.insert(any(MqMessageDedup.class))).thenAnswer(inv -> {
            MqMessageDedup row = inv.getArgument(0);
            String key = row.getMessageId() + "|" + row.getConsumer();
            if (!seen.add(key)) {
                throw new DuplicateKeyException("Duplicate entry '" + key + "' for key 'uk_dedup_message_consumer'");
            }
            return 1;
        });
    }

    private double counter(String name) {
        return registry.get(name).counter().count();
    }

    @Test
    @DisplayName("同一消息投递两次:业务只执行一次,duplicate+1,consumed 只有 1")
    void sameMessageDeliveredTwiceRunsBusinessOnce() {
        simulateUniqueKey();
        AtomicInteger businessRuns = new AtomicInteger();
        TicketEventMessage msg = message("msg-1");

        support.consumeOnce(CONSUMER, msg, m -> businessRuns.incrementAndGet());
        support.consumeOnce(CONSUMER, msg, m -> businessRuns.incrementAndGet());

        assertThat(businessRuns.get()).isEqualTo(1);
        assertThat(counter("mq_event_consumed_total")).isEqualTo(1);
        assertThat(counter("mq_event_duplicate_total")).isEqualTo(1);
        verify(dedupMapper, times(2)).insert(any(MqMessageDedup.class));
    }

    @Test
    @DisplayName("同一消息、不同消费者:各处理一次(唯一键是 messageId + consumer)")
    void sameMessageDifferentConsumersEachRunOnce() {
        simulateUniqueKey();
        List<String> runs = new ArrayList<>();
        TicketEventMessage msg = message("msg-2");

        support.consumeOnce("status-changed-notifier", msg, m -> runs.add("status"));
        support.consumeOnce("assigned-notifier", msg, m -> runs.add("assigned"));
        support.consumeOnce("assigned-notifier", msg, m -> runs.add("assigned-dup"));

        assertThat(runs).containsExactly("status", "assigned");
        assertThat(counter("mq_event_consumed_total")).isEqualTo(2);
        assertThat(counter("mq_event_duplicate_total")).isEqualTo(1);
    }

    @Test
    @DisplayName("首次消费:去重行字段完整(messageId / consumer / eventType / ticketId / traceId / consumedAt)")
    void firstConsumptionWritesFullDedupRow() {
        when(dedupMapper.insert(any(MqMessageDedup.class))).thenReturn(1);
        TicketEventMessage msg = message("msg-3");

        support.consumeOnce(CONSUMER, msg, m -> { });

        ArgumentCaptor<MqMessageDedup> captor = ArgumentCaptor.forClass(MqMessageDedup.class);
        verify(dedupMapper).insert(captor.capture());
        MqMessageDedup row = captor.getValue();
        assertThat(row.getMessageId()).isEqualTo("msg-3");
        assertThat(row.getConsumer()).isEqualTo(CONSUMER);
        assertThat(row.getEventType()).isEqualTo(EventType.STATUS_CHANGED);
        assertThat(row.getTicketId()).isEqualTo(7L);
        assertThat(row.getTraceId()).isEqualTo("trace-msg-3");
        assertThat(row.getConsumedAt()).isEqualTo(TestFixtures.NOW);
    }

    @Test
    @DisplayName("业务抛异常:异常向上传播(触发事务回滚 + 重投),consumed 不计数")
    void businessFailurePropagatesAndDoesNotCount() {
        when(dedupMapper.insert(any(MqMessageDedup.class))).thenReturn(1);
        TicketEventMessage msg = message("msg-4");

        assertThatThrownBy(() -> support.consumeOnce(CONSUMER, msg, m -> {
            throw new IllegalStateException("下游通知失败");
        })).isInstanceOf(IllegalStateException.class);

        assertThat(registry.find("mq_event_consumed_total").counter().count()).isZero();
        assertThat(registry.find("mq_event_duplicate_total").counter().count()).isZero();
    }

    @Test
    @DisplayName("重复消息:业务不执行,也不抛异常(重复不是错误,消息应被正常 ack)")
    void duplicateIsSilentlySkipped() {
        when(dedupMapper.insert(any(MqMessageDedup.class))).thenThrow(new DuplicateKeyException("dup"));
        AtomicInteger runs = new AtomicInteger();

        support.consumeOnce(CONSUMER, message("msg-5"), m -> runs.incrementAndGet());

        assertThat(runs.get()).isZero();
        assertThat(counter("mq_event_duplicate_total")).isEqualTo(1);
    }

    @Test
    @DisplayName("traceId 从消息体带进 MDC,消费结束后清掉(线程复用不串号)")
    void traceIdPropagatedToMdcAndCleared() {
        when(dedupMapper.insert(any(MqMessageDedup.class))).thenReturn(1);
        List<String> seenInBusiness = new ArrayList<>();

        support.consumeOnce(CONSUMER, message("msg-6"), m -> seenInBusiness.add(MDC.get("traceId")));

        assertThat(seenInBusiness).containsExactly("trace-msg-6");
        assertThat(MDC.get("traceId")).isNull();
    }

    @Test
    @DisplayName("消息体没有 traceId:用 mq-<messageId> 兜底,日志仍可对得上消息")
    void missingTraceIdFallsBackToMessageId() {
        when(dedupMapper.insert(any(MqMessageDedup.class))).thenReturn(1);
        TicketEventMessage msg = message("msg-7");
        msg.setTraceId(null);
        List<String> seen = new ArrayList<>();

        support.consumeOnce(CONSUMER, msg, m -> seen.add(MDC.get("traceId")));

        assertThat(seen).containsExactly("mq-msg-7");
    }
}
