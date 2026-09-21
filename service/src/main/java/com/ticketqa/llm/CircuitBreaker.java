package com.ticketqa.llm;

import java.time.Clock;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 最小熔断器(ADR-004):连续失败 N 次 → 打开 T 秒 → 到期自动闭合、计数清零。
 * 没有半开状态:到期后第一批请求会同时放行去探测,失败满 N 次再次打开。
 * 不引 Resilience4j(ADR-010):40 行能讲清楚的东西,不值得为它引入一个框架的内部状态机。
 *
 * 线程安全:AtomicInteger 做计数,volatile 做开关时间戳。
 * 并发下 threshold 附近可能多打开一次,可接受——这是熔断器,不是账本。
 */
public class CircuitBreaker {

    private final int failureThreshold;
    private final long openMillis;
    private final Clock clock;

    private final AtomicInteger consecutiveFailures = new AtomicInteger();
    private volatile long openUntilEpochMs = 0L;

    public CircuitBreaker(int failureThreshold, long openMillis, Clock clock) {
        this.failureThreshold = failureThreshold;
        this.openMillis = openMillis;
        this.clock = clock;
    }

    public boolean isOpen() {
        return clock.millis() < openUntilEpochMs;
    }

    public void recordSuccess() {
        consecutiveFailures.set(0);
    }

    /** @return 这次失败是否恰好触发了熔断(用于打 llm_circuit_open_total) */
    public boolean recordFailure() {
        int n = consecutiveFailures.incrementAndGet();
        if (n >= failureThreshold) {
            openUntilEpochMs = clock.millis() + openMillis;
            consecutiveFailures.set(0);
            return true;
        }
        return false;
    }

    public int consecutiveFailures() {
        return consecutiveFailures.get();
    }

    public Instant openUntil() {
        return Instant.ofEpochMilli(openUntilEpochMs);
    }
}
