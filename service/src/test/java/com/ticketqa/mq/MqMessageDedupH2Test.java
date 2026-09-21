package com.ticketqa.mq;

import com.ticketqa.domain.entity.MqMessageDedup;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.mapper.MqMessageDedupMapper;
import com.ticketqa.support.H2SliceTest;
import com.ticketqa.support.TestFixtures;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * 去重表唯一键(ADR-003)在真实 SQL 上的行为:
 * IdempotentConsumerSupport 捕获的是 Spring 翻译后的 DuplicateKeyException,
 * 这里验证"同一 (message_id, consumer) 插两次"确实抛的是这个类型——否则幂等逻辑会因为 catch 不到而把重复当异常。
 */
@H2SliceTest
class MqMessageDedupH2Test {

    @Autowired
    private MqMessageDedupMapper mapper;

    private static MqMessageDedup row(String messageId, String consumer) {
        MqMessageDedup r = new MqMessageDedup();
        r.setMessageId(messageId);
        r.setConsumer(consumer);
        r.setEventType(EventType.STATUS_CHANGED);
        r.setTicketId(1L);
        r.setTraceId("t");
        r.setConsumedAt(TestFixtures.NOW);
        return r;
    }

    @Test
    @DisplayName("同一 messageId + consumer 插入两次:第二次抛 DuplicateKeyException(不是别的异常)")
    void duplicateInsertThrowsDuplicateKeyException() {
        assertThat(mapper.insert(row("m-1", "status-changed-notifier"))).isEqualTo(1);
        assertThatThrownBy(() -> mapper.insert(row("m-1", "status-changed-notifier")))
                .isInstanceOf(DuplicateKeyException.class);
    }

    @Test
    @DisplayName("同一 messageId、不同 consumer:各自插入成功(唯一键是复合键)")
    void differentConsumersDoNotCollide() {
        assertThat(mapper.insert(row("m-2", "status-changed-notifier"))).isEqualTo(1);
        assertThat(mapper.insert(row("m-2", "assigned-notifier"))).isEqualTo(1);
    }
}
