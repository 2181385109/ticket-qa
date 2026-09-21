package com.ticketqa.mq.consumer;

import com.ticketqa.config.RabbitConfig;
import com.ticketqa.mq.IdempotentConsumerSupport;
import com.ticketqa.mq.message.TicketEventMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * 状态变更通知消费者:模拟"通知客户工单状态已变化"。
 * 通知本身只打日志——本项目的被测点是链路是否通、消费是否幂等,不是通知渠道。
 */
@Component
public class StatusChangedConsumer {

    private static final Logger log = LoggerFactory.getLogger(StatusChangedConsumer.class);
    public static final String NAME = "status-changed-notifier";

    private final IdempotentConsumerSupport idempotent;

    public StatusChangedConsumer(IdempotentConsumerSupport idempotent) {
        this.idempotent = idempotent;
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_STATUS_CHANGED)
    public void onMessage(TicketEventMessage message) {
        idempotent.consumeOnce(NAME, message, m ->
                log.info("[通知客户] 工单 {} 状态 {} -> {},操作者={},来源={}",
                        m.getTicketNo(), m.getFromStatus(), m.getToStatus(), m.getOperatorName(), m.getSource()));
    }
}
