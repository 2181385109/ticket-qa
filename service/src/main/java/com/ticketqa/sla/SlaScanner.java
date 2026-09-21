package com.ticketqa.sla;

import com.ticketqa.common.TraceIdFilter;
import com.ticketqa.config.AppProperties;
import com.ticketqa.mapper.TicketMapper;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.UUID;

/**
 * SLA 扫描器:定时找出超时未响应的工单,逐张交给 SlaEscalationService 升级。
 *
 * 两层防重复(ADR-006):
 *   1. Redis 锁(SET NX PX):多实例部署时同一时刻只有一个实例在扫,减少无谓的条件更新冲突;
 *      Redis 不可用时**照常扫描**(fail-open)并打点——正确性不依赖这把锁,依赖的是第 2 层。
 *   2. 数据库条件更新:同一工单绝不会被升级两次。这一层才是保证。
 *
 * @Scheduled(fixedDelayString):上一轮结束后再等 N 毫秒开始下一轮,不会重叠。
 * 默认单线程调度器,所以这个方法本身也不会并发执行。
 */
@Component
public class SlaScanner {

    private static final Logger log = LoggerFactory.getLogger(SlaScanner.class);
    private static final String LOCK_KEY = "ticketqa:lock:sla-scan";
    private static final DefaultRedisScript<Long> RELEASE_IF_OWNER = new DefaultRedisScript<>(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end", Long.class);

    private final TicketMapper ticketMapper;
    private final SlaEscalationService escalationService;
    private final StringRedisTemplate redis;
    private final AppProperties props;
    private final Clock clock;
    private final String instanceId = UUID.randomUUID().toString();
    private final Counter scanCounter;
    private final Counter lockUnavailableCounter;

    public SlaScanner(TicketMapper ticketMapper, SlaEscalationService escalationService, StringRedisTemplate redis,
                      AppProperties props, Clock clock, MeterRegistry registry) {
        this.ticketMapper = ticketMapper;
        this.escalationService = escalationService;
        this.redis = redis;
        this.props = props;
        this.clock = clock;
        this.scanCounter = Counter.builder("sla_scan_total").description("SLA 扫描轮次").register(registry);
        this.lockUnavailableCounter = Counter.builder("sla_scan_lock_unavailable_total")
                .description("Redis 不可用、未持锁直接扫描的轮次").register(registry);
    }

    @Scheduled(fixedDelayString = "${app.sla.scan-interval-ms}", initialDelayString = "${app.sla.scan-interval-ms}")
    public void scheduledScan() {
        MDC.put(TraceIdFilter.MDC_KEY, "sla-" + TraceIdFilter.newTraceId());
        try {
            scanOnce();
        } catch (Exception e) {
            log.error("SLA 扫描异常", e);
        } finally {
            MDC.remove(TraceIdFilter.MDC_KEY);
        }
    }

    /** 也暴露给管理接口手动触发,便于联调和测试时不用等定时器。返回本轮实际升级的工单数。 */
    public int scanOnce() {
        scanCounter.increment();
        Boolean locked = tryLock();
        if (Boolean.FALSE.equals(locked)) {
            log.debug("SLA 扫描:其他实例持锁,本轮跳过");
            return 0;
        }
        try {
            LocalDateTime now = LocalDateTime.now(clock);
            List<Long> ids = ticketMapper.selectSlaOverdueIds(now, props.sla().scanBatchSize());
            if (ids.isEmpty()) {
                return 0;
            }
            log.info("SLA 扫描命中 {} 张工单 now={}", ids.size(), now);
            int escalated = 0;
            for (Long id : ids) {
                try {
                    if (escalationService.escalate(id, now)) {
                        escalated++;
                    }
                } catch (Exception e) {
                    log.error("SLA 升级失败 ticketId={}", id, e);
                }
            }
            return escalated;
        } finally {
            if (Boolean.TRUE.equals(locked)) {
                unlock();
            }
        }
    }

    /** @return TRUE 拿到锁;FALSE 被别人持有;null Redis 不可用(fail-open) */
    private Boolean tryLock() {
        try {
            Boolean ok = redis.opsForValue().setIfAbsent(LOCK_KEY, instanceId, Duration.ofSeconds(props.sla().lockTtlSeconds()));
            return Boolean.TRUE.equals(ok);
        } catch (Exception e) {
            lockUnavailableCounter.increment();
            log.warn("Redis 不可用,SLA 扫描不加锁继续执行: {}", e.getMessage());
            return null;
        }
    }

    private void unlock() {
        try {
            redis.execute(RELEASE_IF_OWNER, List.of(LOCK_KEY), instanceId);
        } catch (Exception e) {
            log.warn("释放 SLA 扫描锁失败(锁会在 TTL 到期后自动消失): {}", e.getMessage());
        }
    }
}
