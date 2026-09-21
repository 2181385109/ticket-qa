package com.ticketqa.llm;

import com.ticketqa.support.MutableClock;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 熔断器(ADR-004):连续失败 5 次 → 打开 60 秒 → 到期自动闭合。
 *
 * 两个维度的边界值:
 *   失败次数:4(闭合)/ 5(打开)
 *   打开时长:59.999s(仍打开)/ 60s 整(闭合,isOpen 用的是 now < openUntil,上界开)
 * "连续"的语义:中间只要有一次成功,计数归零。
 */
class CircuitBreakerTest {

    private static final int THRESHOLD = 5;
    private static final long OPEN_MS = 60_000;

    private MutableClock clock;
    private CircuitBreaker breaker;

    @BeforeEach
    void setUp() {
        clock = MutableClock.at(Instant.parse("2026-09-20T02:00:00Z"));
        breaker = new CircuitBreaker(THRESHOLD, OPEN_MS, clock);
    }

    @Test
    @DisplayName("初始闭合,连续 4 次失败仍闭合")
    void fourFailuresStayClosed() {
        assertThat(breaker.isOpen()).isFalse();
        for (int i = 1; i <= THRESHOLD - 1; i++) {
            assertThat(breaker.recordFailure()).as("第 %d 次失败不应触发", i).isFalse();
        }
        assertThat(breaker.isOpen()).isFalse();
        assertThat(breaker.consecutiveFailures()).isEqualTo(4);
    }

    @Test
    @DisplayName("第 5 次失败恰好触发:recordFailure 返回 true,状态打开,计数清零")
    void fifthFailureTrips() {
        for (int i = 0; i < THRESHOLD - 1; i++) {
            breaker.recordFailure();
        }
        assertThat(breaker.recordFailure()).isTrue();
        assertThat(breaker.isOpen()).isTrue();
        assertThat(breaker.consecutiveFailures()).isZero();
        assertThat(breaker.openUntil()).isEqualTo(clock.instant().plusMillis(OPEN_MS));
    }

    @Test
    @DisplayName("中间一次成功把计数清零:4 失败 + 1 成功 + 4 失败 不触发")
    void successResetsConsecutiveCount() {
        for (int i = 0; i < 4; i++) {
            breaker.recordFailure();
        }
        breaker.recordSuccess();
        assertThat(breaker.consecutiveFailures()).isZero();
        for (int i = 0; i < 4; i++) {
            assertThat(breaker.recordFailure()).isFalse();
        }
        assertThat(breaker.isOpen()).isFalse();
    }

    @Test
    @DisplayName("打开 59.999 秒时仍然打开;满 60 秒自动闭合")
    void closesExactlyAfterOpenWindow() {
        for (int i = 0; i < THRESHOLD; i++) {
            breaker.recordFailure();
        }
        clock.advance(Duration.ofMillis(OPEN_MS - 1));
        assertThat(breaker.isOpen()).as("差 1ms 仍应打开").isTrue();
        clock.advance(Duration.ofMillis(1));
        assertThat(breaker.isOpen()).as("到期即闭合(now < openUntil 不成立)").isFalse();
    }

    @Test
    @DisplayName("恢复后没有半开状态:再次连续 5 次失败才会再打开")
    void reopensOnlyAfterAnotherFullRun() {
        for (int i = 0; i < THRESHOLD; i++) {
            breaker.recordFailure();
        }
        clock.advance(Duration.ofMillis(OPEN_MS));
        assertThat(breaker.isOpen()).isFalse();
        for (int i = 0; i < THRESHOLD - 1; i++) {
            assertThat(breaker.recordFailure()).isFalse();
        }
        assertThat(breaker.isOpen()).isFalse();
        assertThat(breaker.recordFailure()).isTrue();
        assertThat(breaker.isOpen()).isTrue();
    }

    @Test
    @DisplayName("阈值为 1 的退化情况:第一次失败就打开")
    void thresholdOneTripsImmediately() {
        CircuitBreaker single = new CircuitBreaker(1, OPEN_MS, clock);
        assertThat(single.recordFailure()).isTrue();
        assertThat(single.isOpen()).isTrue();
    }
}
