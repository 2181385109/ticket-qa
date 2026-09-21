package com.ticketqa.mq;

import com.ticketqa.common.TraceIdFilter;
import com.ticketqa.domain.entity.MqMessageDedup;
import com.ticketqa.mapper.MqMessageDedupMapper;
import com.ticketqa.mq.message.TicketEventMessage;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.LocalDateTime;
import java.util.function.Consumer;

/**
 * 消费端幂等(ADR-003):
 *   1. 在事务里先 INSERT 去重表 (message_id, consumer) 唯一键
 *   2. 唯一键冲突 → 这条消息已经被本消费者处理过,直接返回
 *   3. 插入成功 → 执行业务;业务抛异常则整个事务回滚,去重记录一起消失,消息重投后还能再处理
 *
 * 为什么是 MySQL 表而不是 Redis setnx:去重记录和业务写在同一个本地事务里,要么都成功要么都不存在;
 * Redis 做不到和 MySQL 事务原子,会出现"setnx 成功、业务失败、消息永远不再被处理"的窗口。
 *
 * 单独一个 Bean:@RabbitListener 方法只做"收消息",事务边界放在这里,避免监听器方法上叠 @Transactional
 * 引出的代理顺序问题。
 */
@Component
public class IdempotentConsumerSupport {

    private static final Logger log = LoggerFactory.getLogger(IdempotentConsumerSupport.class);

    private final MqMessageDedupMapper dedupMapper;
    private final Clock clock;
    private final Counter consumedCounter;
    private final Counter duplicateCounter;

    public IdempotentConsumerSupport(MqMessageDedupMapper dedupMapper, Clock clock, MeterRegistry registry) {
        this.dedupMapper = dedupMapper;
        this.clock = clock;
        this.consumedCounter = Counter.builder("mq_event_consumed_total")
                .description("首次消费成功的消息数").register(registry);
        this.duplicateCounter = Counter.builder("mq_event_duplicate_total")
                .description("被去重表拦下的重复消息数").register(registry);
    }

    /**
     * @param consumerName 消费者标识,同一条消息可被不同消费者各处理一次
     * @param business     真正的业务逻辑,在同一个事务里执行
     */
    @Transactional(rollbackFor = Exception.class)
    public void consumeOnce(String consumerName, TicketEventMessage message, Consumer<TicketEventMessage> business) {
        MDC.put(TraceIdFilter.MDC_KEY, message.getTraceId() == null ? "mq-" + message.getMessageId() : message.getTraceId());
        try {
            if (!tryMark(consumerName, message)) {
                duplicateCounter.increment();
                log.warn("重复消息,跳过 consumer={} messageId={} type={}", consumerName, message.getMessageId(), message.getEventType());
                return;
            }
            business.accept(message);
            consumedCounter.increment();
        } finally {
            MDC.remove(TraceIdFilter.MDC_KEY);
        }
    }

    private boolean tryMark(String consumerName, TicketEventMessage message) {
        MqMessageDedup row = new MqMessageDedup();
        row.setMessageId(message.getMessageId());
        row.setConsumer(consumerName);
        row.setEventType(message.getEventType());
        row.setTicketId(message.getTicketId());
        row.setTraceId(message.getTraceId());
        row.setConsumedAt(LocalDateTime.now(clock));
        try {
            dedupMapper.insert(row);
            return true;
        } catch (DuplicateKeyException e) {
            // MySQL 里一条失败的 INSERT 不会让整个事务失效,可以继续用这个事务(PostgreSQL 则不行)
            return false;
        }
    }
}
