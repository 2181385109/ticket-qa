package com.ticketqa.ticket;

import com.ticketqa.support.TestFixtures;
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
import org.springframework.data.redis.core.script.RedisScript;

import java.time.Duration;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 抢单前置锁(ADR-016 第三层)。判定表:
 *
 *   SET NX 结果      | 返回               | 计数
 *   TRUE            | Optional.of(token) | acquired+1
 *   FALSE(被占)    | Optional.empty()   | rejected+1
 *   抛异常(Redis 挂)| Optional.of("")    | unavailable+1(fail-open)
 *
 * 以及 release:空 token 不碰 Redis;真 token 用 Lua 比较后删;Redis 异常只记日志不抛。
 */
@ExtendWith(MockitoExtension.class)
class GrabLockTest {

    @Mock
    private StringRedisTemplate redis;
    @Mock
    private ValueOperations<String, String> ops;

    private SimpleMeterRegistry registry;
    private GrabLock lock;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        lock = new GrabLock(redis, TestFixtures.appProperties(), registry);
    }

    private double counter(String name) {
        return registry.find(name).counter() == null ? 0 : registry.find(name).counter().count();
    }

    @Test
    @DisplayName("SET NX 成功:返回非空 token,key 带工单 id,TTL 取自配置,acquired+1")
    void acquired() {
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.setIfAbsent(eq("ticketqa:lock:grab:42"), anyString(), eq(Duration.ofMillis(3000)))).thenReturn(true);

        Optional<String> token = lock.tryAcquire(42L);

        assertThat(token).isPresent();
        assertThat(token.get()).isNotEmpty();
        assertThat(counter("grab_lock_acquired_total")).isEqualTo(1);
        assertThat(counter("grab_lock_rejected_total")).isZero();
    }

    @Test
    @DisplayName("SET NX 返回 false(别人持有):Optional.empty,rejected+1——这就是削峰掉的那部分请求")
    void rejected() {
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(false);

        assertThat(lock.tryAcquire(42L)).isEmpty();
        assertThat(counter("grab_lock_rejected_total")).isEqualTo(1);
    }

    @Test
    @DisplayName("Redis 抛异常:fail-open 返回空串 token,unavailable+1,不向上抛——正确性由条件 UPDATE 兜底")
    void unavailableFailsOpen() {
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.setIfAbsent(anyString(), anyString(), any(Duration.class)))
                .thenThrow(new RedisConnectionFailureException("Connection refused"));

        Optional<String> token = lock.tryAcquire(42L);

        assertThat(token).contains("");
        assertThat(counter("grab_lock_unavailable_total")).isEqualTo(1);
    }

    @Test
    @DisplayName("release:空 token(fail-open 那次)不碰 Redis;真 token 用 Lua 脚本按 key + token 删")
    void releaseOnlyOwnLock() {
        lock.release(42L, "");
        lock.release(42L, null);
        verify(redis, never()).execute(any(RedisScript.class), anyList(), any());

        lock.release(42L, "tok");
        verify(redis).execute(any(RedisScript.class), eq(List.of("ticketqa:lock:grab:42")), eq("tok"));
    }

    @Test
    @DisplayName("release 时 Redis 异常:吞掉只记日志(锁会随 TTL 消失),不能让已提交的抢单变成 500")
    void releaseSwallowsRedisErrors() {
        when(redis.execute(any(RedisScript.class), anyList(), any()))
                .thenThrow(new RedisConnectionFailureException("Connection reset"));
        lock.release(42L, "tok");
    }
}
