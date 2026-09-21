package com.ticketqa.ticket;

import com.ticketqa.config.AppProperties;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 抢单的前置 Redis 锁(ADR-016 的第三层,也是唯一"可有可无"的一层)。
 *
 * 作用是削峰:同一张工单同一时刻只放一个请求去数据库,其余请求在拿到数据库连接之前就以 409 返回,
 * 既不占 HikariCP 连接、也不在 InnoDB 行锁上排队。压测里 20 线程抢同一张单,
 * 修复前 20 个事务全部排进行锁队列(第 12 个要等 160 ms),有了这一层只有 1 个事务进库。
 *
 * 它明确**不是**正确性保证:
 *   - Redis 不可用 → fail-open,直接放行,靠条件 UPDATE 兜底(和 SlaScanner 的锁一个思路);
 *   - TTL 到期后锁自动消失,持锁者的事务若还没提交,后来者进库也只会在条件 UPDATE 上得到 0 行;
 *   - 单节点 Redis 的 SET NX 在主从切换时可能丢锁——同样由条件 UPDATE 兜底。
 * 三种情况下都只是"多一个请求进库",不会多分配一次。
 */
@Component
public class GrabLock {

    private static final Logger log = LoggerFactory.getLogger(GrabLock.class);
    private static final String KEY_PREFIX = "ticketqa:lock:grab:";
    /** 只删自己加的锁:比较 value 再 DEL,两步在 Lua 里原子执行 */
    private static final DefaultRedisScript<Long> RELEASE_IF_OWNER = new DefaultRedisScript<>(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end", Long.class);

    private final StringRedisTemplate redis;
    private final Duration ttl;
    private final Counter acquiredCounter;
    private final Counter rejectedCounter;
    private final Counter unavailableCounter;

    public GrabLock(StringRedisTemplate redis, AppProperties props, MeterRegistry registry) {
        this.redis = redis;
        this.ttl = Duration.ofMillis(props.ticket().grabLockTtlMs());
        this.acquiredCounter = Counter.builder("grab_lock_acquired_total")
                .description("抢单前置锁拿到的次数(进库的请求数)").register(registry);
        this.rejectedCounter = Counter.builder("grab_lock_rejected_total")
                .description("抢单前置锁被占、未进库直接 409 的次数(削峰量)").register(registry);
        this.unavailableCounter = Counter.builder("grab_lock_unavailable_total")
                .description("Redis 不可用、fail-open 放行的次数").register(registry);
    }

    /**
     * 尝试加锁。
     *
     * @return {@code Optional.of(token)} 拿到锁;{@code Optional.empty()} 被别人持有;
     *         {@code Optional.of("")} Redis 不可用(fail-open,调用方照常进库,释放时跳过)
     */
    public Optional<String> tryAcquire(Long ticketId) {
        String token = UUID.randomUUID().toString();
        try {
            Boolean ok = redis.opsForValue().setIfAbsent(KEY_PREFIX + ticketId, token, ttl);
            if (Boolean.TRUE.equals(ok)) {
                acquiredCounter.increment();
                return Optional.of(token);
            }
            rejectedCounter.increment();
            return Optional.empty();
        } catch (Exception e) {
            unavailableCounter.increment();
            log.warn("Redis 不可用,抢单不加前置锁直接走条件更新 ticketId={}: {}", ticketId, e.getMessage());
            return Optional.of("");
        }
    }

    public void release(Long ticketId, String token) {
        if (token == null || token.isEmpty()) {
            return;
        }
        try {
            redis.execute(RELEASE_IF_OWNER, List.of(KEY_PREFIX + ticketId), token);
        } catch (Exception e) {
            log.warn("释放抢单锁失败(锁会在 TTL 到期后自动消失) ticketId={}: {}", ticketId, e.getMessage());
        }
    }
}
