package com.ticketqa.ticket;

import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.ThreadLocalRandom;

/**
 * 业务单号:{@code T} + 日期 + {@code -} + 16 个十六进制字符(64 bit 随机量)。
 *
 * 第一版只取 UUID 前 8 位(32 bit),压测当天创建到 ~9 万张时撞了两次 uk_ticket_no(KI-011):
 * 生日碰撞的期望次数 ≈ n² / 2^(b+1),b=32、n=9 万 → 0.9 次,是必然事件不是偶发。
 * 换成 64 bit 后同样 n 的期望 ≈ 2×10⁻¹⁰;要把期望推到 0.5 次需要一天创建 43 亿张(ADR-019)。
 *
 * 随机源用 ThreadLocalRandom 而不是 SecureRandom:单号不承担鉴权(鉴权只认 X-User-Id),
 * 不需要不可预测性;SecureRandom 在高并发下有锁竞争,压测拐点就在数据访问层,没必要再加一处。
 * 库里 uk_ticket_no 仍然保留:它是最后一道防线,碰撞时宁可 500 也不能出两张同号单。
 */
@Component
public class TicketNoGenerator {

    private static final DateTimeFormatter DAY = DateTimeFormatter.ofPattern("yyyyMMdd");
    /** 单号总长 1 + 8 + 1 + 16 = 26,列定义 VARCHAR(32) */
    static final int RANDOM_HEX_LEN = 16;

    public String generate(LocalDateTime now) {
        long random = ThreadLocalRandom.current().nextLong();
        String hex = Long.toHexString(random).toUpperCase();
        // toHexString 不补前导零,固定补到 16 位,单号等长便于肉眼对齐和索引前缀
        return "T" + now.format(DAY) + "-" + "0".repeat(RANDOM_HEX_LEN - hex.length()) + hex;
    }
}
