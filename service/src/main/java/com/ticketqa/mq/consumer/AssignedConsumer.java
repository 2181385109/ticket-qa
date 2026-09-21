package com.ticketqa.mq.consumer;

import com.ticketqa.config.RabbitConfig;
import com.ticketqa.mq.IdempotentConsumerSupport;
import com.ticketqa.mq.message.TicketEventMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * 分配通知消费者:模拟"通知坐席你有新工单"。
 */
@Component
public class AssignedConsumer {

    private static final Logger log = LoggerFactory.getLogger(AssignedConsumer.class);
    public static final String NAME = "assigned-notifier";

    private final IdempotentConsumerSupport idempotent;

    public AssignedConsumer(IdempotentConsumerSupport idempotent) {
        this.idempotent = idempotent;
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_ASSIGNED)
    public void onMessage(TicketEventMessage message) {
        idempotent.consumeOnce(NAME, message, m ->
                log.info("[通知坐席] 坐席 {} 被分配工单 {},操作者={}",
                        m.getAssigneeId(), m.getTicketNo(), m.getOperatorName()));
    }
}
