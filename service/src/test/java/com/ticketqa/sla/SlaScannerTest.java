package com.ticketqa.sla;

import com.ticketqa.mapper.TicketMapper;
import com.ticketqa.support.TestFixtures;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * SLA 扫描器:锁 + 批量交给 SlaEscalationService。
 *
 * 场景法,四个场景:
 *   S1 拿到锁,扫到 N 张 → 逐张升级,数量正确,最后释放锁
 *   S2 锁被别的实例持有 → 本轮跳过,不查库
 *   S3 Redis 不可用 → fail-open:不加锁照常扫,lock_unavailable+1,最后不尝试释放
 *   S4 某一张升级抛异常 → 记日志继续下一张,返回值只计成功的
 * 另外验证:传给 mapper 的 now 来自注入的 Clock(这是闭区间边界能被精确测到的前提,ADR-006)。
 */
@ExtendWith(MockitoExtension.class)
class SlaScannerTest {

    @Mock
    private TicketMapper ticketMapper;
    @Mock
    private SlaEscalationService escalationService;
    @Mock
    private StringRedisTemplate redis;
    @Mock
    private ValueOperations<String, String> valueOps;

    private MeterRegistry registry;
    private SlaScanner scanner;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        scanner = new SlaScanner(ticketMapper, escalationService, redis, TestFixtures.appProperties(),
                TestFixtures.fixedClock(), registry);
    }

    private void lockAcquired(boolean ok) {
        when(redis.opsForValue()).thenReturn(valueOps);
        when(valueOps.setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(ok);
    }

    private double counter(String name) {
        return registry.find(name).counter() == null ? 0 : registry.find(name).counter().count();
    }

    @Test
    @DisplayName("S1 拿到锁:now 取自 Clock,批量大小取自配置,逐张升级,释放锁")
    void scansWithLockAndClockNow() {
        lockAcquired(true);
        when(ticketMapper.selectSlaOverdueIds(TestFixtures.NOW, 100)).thenReturn(List.of(1L, 2L, 3L));
        when(escalationService.escalate(anyLong(), eq(TestFixtures.NOW))).thenReturn(true, false, true);

        int escalated = scanner.scanOnce();

        assertThat(escalated).isEqualTo(2);
        verify(ticketMapper).selectSlaOverdueIds(TestFixtures.NOW, 100);
        verify(escalationService).escalate(1L, TestFixtures.NOW);
        verify(escalationService).escalate(2L, TestFixtures.NOW);
        verify(escalationService).escalate(3L, TestFixtures.NOW);
        verify(redis).execute(any(), eq(List.of("ticketqa:lock:sla-scan")), anyString());
        assertThat(counter("sla_scan_total")).isEqualTo(1);
        assertThat(counter("sla_scan_lock_unavailable_total")).isZero();
    }

    @Test
    @DisplayName("S1' 拿到锁但没有超时单:返回 0,不调升级服务")
    void nothingOverdue() {
        lockAcquired(true);
        when(ticketMapper.selectSlaOverdueIds(any(LocalDateTime.class), anyInt())).thenReturn(List.of());

        assertThat(scanner.scanOnce()).isZero();

        verify(escalationService, never()).escalate(anyLong(), any());
    }

    @Test
    @DisplayName("S2 锁被其他实例持有:本轮跳过,不查库")
    void skipsWhenLockHeldElsewhere() {
        lockAcquired(false);

        assertThat(scanner.scanOnce()).isZero();

        verify(ticketMapper, never()).selectSlaOverdueIds(any(), anyInt());
        verify(redis, never()).execute(any(), any(), any());
        assertThat(counter("sla_scan_total")).isEqualTo(1);
    }

    @Test
    @DisplayName("S3 Redis 不可用:fail-open 照常扫描,lock_unavailable+1,不尝试释放锁")
    void failsOpenWhenRedisDown() {
        when(redis.opsForValue()).thenThrow(new RedisConnectionFailureException("Connection refused"));
        when(ticketMapper.selectSlaOverdueIds(TestFixtures.NOW, 100)).thenReturn(List.of(9L));
        when(escalationService.escalate(9L, TestFixtures.NOW)).thenReturn(true);

        assertThat(scanner.scanOnce()).isEqualTo(1);

        assertThat(counter("sla_scan_lock_unavailable_total")).isEqualTo(1);
        verify(redis, never()).execute(any(), any(), any());
    }

    @Test
    @DisplayName("S4 某一张升级抛异常:不影响同批其他工单,返回值只计成功的")
    void oneFailureDoesNotStopTheBatch() {
        lockAcquired(true);
        when(ticketMapper.selectSlaOverdueIds(TestFixtures.NOW, 100)).thenReturn(List.of(1L, 2L, 3L));
        when(escalationService.escalate(1L, TestFixtures.NOW)).thenReturn(true);
        when(escalationService.escalate(2L, TestFixtures.NOW)).thenThrow(new RuntimeException("死锁"));
        when(escalationService.escalate(3L, TestFixtures.NOW)).thenReturn(true);

        assertThat(scanner.scanOnce()).isEqualTo(2);

        verify(escalationService, times(3)).escalate(anyLong(), eq(TestFixtures.NOW));
        verify(redis).execute(any(), eq(List.of("ticketqa:lock:sla-scan")), anyString());
    }

    @Test
    @DisplayName("scheduledScan 包住异常:查库抛错不会让定时线程死掉")
    void scheduledScanSwallowsExceptions() {
        lockAcquired(true);
        when(ticketMapper.selectSlaOverdueIds(any(), anyInt())).thenThrow(new RuntimeException("db down"));

        scanner.scheduledScan();   // 不抛即通过

        verify(redis).execute(any(), any(), anyString());   // finally 里仍然释放锁
    }
}
