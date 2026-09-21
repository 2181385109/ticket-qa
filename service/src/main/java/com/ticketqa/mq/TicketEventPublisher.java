package com.ticketqa.mq;

import com.ticketqa.config.RabbitConfig;
import com.ticketqa.mq.message.TicketEventMessage;
import com.ticketqa.ticket.event.TicketDomainEvent;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

/**
 * 领域事件 → MQ 消息。
 *
 * @TransactionalEventListener(AFTER_COMMIT):只有发布事件的那个事务成功提交后才执行。
 * 这样消费者收到消息时,工单的新状态和审计日志一定已经在库里,不会读到"消息先到、数据还没提交"的中间态。
 *
 * 代价(ADR-002):提交成功但发送失败,这条消息就丢了——这里只记日志和打点,不做本地消息表 / outbox。
 * fallbackExecution = true:万一在没有事务的上下文里发布事件,立即发送而不是静默丢弃。
 */
@Component
public class TicketEventPublisher {

    private static final Logger log = LoggerFactory.getLogger(TicketEventPublisher.class);

    private final RabbitTemplate rabbitTemplate;
    private final Counter publishedCounter;
    private final Counter publishFailedCounter;

    public TicketEventPublisher(RabbitTemplate rabbitTemplate, MeterRegistry registry) {
        this.rabbitTemplate = rabbitTemplate;
        this.publishedCounter = Counter.builder("mq_event_published_total")
                .description("发布到 RabbitMQ 的事件数").register(registry);
        this.publishFailedCounter = Counter.builder("mq_event_publish_failed_total")
                .description("事务已提交但 MQ 发送失败的事件数").register(registry);
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onTicketEvent(TicketDomainEvent event) {
        TicketEventMessage message = TicketEventMessage.from(event);
        try {
            rabbitTemplate.convertAndSend(RabbitConfig.EXCHANGE, event.type().routingKey(), message);
            publishedCounter.increment();
            log.info("MQ 发送 type={} ticketId={} messageId={}", event.type(), event.ticketId(), message.getMessageId());
        } catch (AmqpException e) {
            publishFailedCounter.increment();
            log.error("MQ 发送失败(事务已提交,消息丢失) type={} ticketId={} messageId={}",
                    event.type(), event.ticketId(), message.getMessageId(), e);
        }
    }
}
