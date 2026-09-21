package com.ticketqa.mq.consumer;

import com.ticketqa.config.RabbitConfig;
import com.ticketqa.mq.IdempotentConsumerSupport;
import com.ticketqa.mq.message.TicketEventMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * SLA 升级通知消费者:模拟"通知组长有工单超时未响应"。
 */
@Component
public class SlaEscalatedConsumer {

    private static final Logger log = LoggerFactory.getLogger(SlaEscalatedConsumer.class);
    public static final String NAME = "sla-escalated-notifier";

    private final IdempotentConsumerSupport idempotent;

    public SlaEscalatedConsumer(IdempotentConsumerSupport idempotent) {
        this.idempotent = idempotent;
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_SLA_ESCALATED)
    public void onMessage(TicketEventMessage message) {
        idempotent.consumeOnce(NAME, message, m ->
                log.warn("[通知组长] 工单 {} 超过响应时限,已自动升级(原状态 {}),发生于 {}",
                        m.getTicketNo(), m.getFromStatus(), m.getOccurredAt()));
    }
}
