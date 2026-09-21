package com.ticketqa.ticket;

import com.ticketqa.support.TestFixtures;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 业务单号的位宽(KI-011 / ADR-019)。
 *
 * 这是"用统计把缺陷钉死"的写法:同一天、同一毫秒生成 n 个单号,断言无重复。
 * 生日碰撞期望 ≈ n² / 2^(b+1):
 *   b=32(第一版,UUID 前 8 位)  n=100 万 → 期望 116 次,P(无碰撞) ≈ e^-116 ≈ 0——必挂
 *   b=64(现在)                 n=100 万 → 期望 2.7×10⁻⁸——必过
 * 100 万次 ThreadLocalRandom + toHexString 约 1 秒,可以接受;把第一版的算法留在 legacy() 里同场对照,
 * 让"为什么要 64 bit"在测试输出里就能看到,而不是只写在 ADR 里。
 */
class TicketNoGeneratorTest {

    private static final int N = 1_000_000;
    private static final Pattern SHAPE = Pattern.compile("^T\\d{8}-[0-9A-F]{16}$");

    private final TicketNoGenerator generator = new TicketNoGenerator();

    /** 第一版算法(dd1c436 里 TicketService.newTicketNo 的原样),只用于对照 */
    private static String legacy(LocalDateTime now) {
        return "T" + now.format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd")) + "-"
                + UUID.randomUUID().toString().substring(0, 8).toUpperCase();
    }

    @Test
    @DisplayName("形状:T + 8 位日期 + '-' + 16 位大写十六进制,总长 26,定长(前导零补齐)")
    void shape() {
        for (int i = 0; i < 1000; i++) {
            String no = generator.generate(TestFixtures.NOW);
            assertThat(no).hasSize(26).matches(SHAPE).startsWith("T20260920-");
        }
    }

    @Test
    @DisplayName("同一毫秒生成 100 万个单号无重复(64 bit 随机量,碰撞期望 ≈ 2.7×10⁻⁸)")
    void oneMillionInSameMillisecondAreUnique() {
        Set<String> seen = new HashSet<>(N * 2);
        int duplicates = 0;
        for (int i = 0; i < N; i++) {
            if (!seen.add(generator.generate(TestFixtures.NOW))) {
                duplicates++;
            }
        }
        assertThat(duplicates).as("64 bit 单号在 %d 次内的重复数", N).isZero();
    }

    @Test
    @DisplayName("对照:第一版 32 bit 算法在同样 100 万次里必然碰撞(KI-011 的根因就是位宽)")
    void legacy32BitCollidesUnderSameLoad() {
        Set<String> seen = new HashSet<>(N * 2);
        int duplicates = 0;
        for (int i = 0; i < N; i++) {
            if (!seen.add(legacy(TestFixtures.NOW))) {
                duplicates++;
            }
        }
        // 期望 116 次;用 > 0 而不是精确值,避免把一个概率断言写成脆弱断言
        assertThat(duplicates).as("32 bit 单号在 %d 次内的重复数(期望约 116)", N).isPositive();
    }

    @Test
    @DisplayName("跨天前缀不同:日期段来自传入的时刻,不读系统时钟")
    void datePrefixFollowsGivenClock() {
        assertThat(generator.generate(LocalDateTime.of(2026, 12, 31, 23, 59, 59))).startsWith("T20261231-");
        assertThat(generator.generate(LocalDateTime.of(2027, 1, 1, 0, 0, 0))).startsWith("T20270101-");
    }
}
