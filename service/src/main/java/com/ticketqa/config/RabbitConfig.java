package com.ticketqa.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketqa.domain.enums.EventType;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * RabbitMQ 拓扑:一个 topic 交换机,三个队列,按 routing key 绑定。
 * 声明成 Bean 后,Spring AMQP 的 RabbitAdmin 会在首次连接时自动在 Broker 上创建它们(幂等)。
 *
 *   ticket.events ──ticket.status.changed──▶ q.ticket.status-changed
 *                 ──ticket.sla.escalated───▶ q.ticket.sla-escalated
 *                 ──ticket.assigned────────▶ q.ticket.assigned
 */
@Configuration
public class RabbitConfig {

    public static final String EXCHANGE = "ticket.events";
    public static final String QUEUE_STATUS_CHANGED = "q.ticket.status-changed";
    public static final String QUEUE_SLA_ESCALATED = "q.ticket.sla-escalated";
    public static final String QUEUE_ASSIGNED = "q.ticket.assigned";

    @Bean
    public TopicExchange ticketExchange() {
        return new TopicExchange(EXCHANGE, true, false);
    }

    @Bean
    public Queue statusChangedQueue() {
        return QueueBuilder.durable(QUEUE_STATUS_CHANGED).build();
    }

    @Bean
    public Queue slaEscalatedQueue() {
        return QueueBuilder.durable(QUEUE_SLA_ESCALATED).build();
    }

    @Bean
    public Queue assignedQueue() {
        return QueueBuilder.durable(QUEUE_ASSIGNED).build();
    }

    @Bean
    public Binding statusChangedBinding(Queue statusChangedQueue, TopicExchange ticketExchange) {
        return BindingBuilder.bind(statusChangedQueue).to(ticketExchange).with(EventType.STATUS_CHANGED.routingKey());
    }

    @Bean
    public Binding slaEscalatedBinding(Queue slaEscalatedQueue, TopicExchange ticketExchange) {
        return BindingBuilder.bind(slaEscalatedQueue).to(ticketExchange).with(EventType.SLA_ESCALATED.routingKey());
    }

    @Bean
    public Binding assignedBinding(Queue assignedQueue, TopicExchange ticketExchange) {
        return BindingBuilder.bind(assignedQueue).to(ticketExchange).with(EventType.ASSIGNED.routingKey());
    }

    /** 消息体用 JSON 而不是 JDK 序列化:管理台里能直接看懂,Python 消费者也能读。复用 Boot 配好的 ObjectMapper。 */
    @Bean
    public MessageConverter jacksonMessageConverter(ObjectMapper objectMapper) {
        return new Jackson2JsonMessageConverter(objectMapper);
    }

    @Bean
    public RabbitTemplate rabbitTemplate(ConnectionFactory connectionFactory, MessageConverter converter) {
        RabbitTemplate template = new RabbitTemplate(connectionFactory);
        template.setMessageConverter(converter);
        template.setExchange(EXCHANGE);
        return template;
    }
}
