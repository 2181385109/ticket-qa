package com.ticketqa.config;

import com.ticketqa.domain.enums.TicketPriority;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.util.List;
import java.util.Map;

/**
 * application.yml 里 app.* 的类型安全绑定。
 * 启动时 Spring 把配置树反射填进这个对象,@Validated 让非法配置在启动阶段就失败,而不是运行到一半才炸。
 * 用 record 写成不可变结构:配置一旦加载不应再被改。
 */
@Validated
@ConfigurationProperties(prefix = "app")
public record AppProperties(
        @NotBlank String timeZone,
        @NotNull Sla sla,
        @NotNull Ticket ticket,
        @NotNull Attachment attachment) {

    public record Sla(
            @NotEmpty Map<TicketPriority, Integer> responseMinutes,
            @Min(1000) long scanIntervalMs,
            @Min(1) int scanBatchSize,
            @Min(1) int lockTtlSeconds) {
    }

    /**
     * grabLockTtlMs:抢单前置 Redis 锁的 TTL(ADR-016)。只需覆盖一次抢单事务的时长(无竞争 ~13 ms,
     * 连接池排满时最多 connection-timeout 5 s);锁到期后别人进来也只会在条件 UPDATE 上得到 0 行,不影响正确性。
     */
    public record Ticket(@Min(0) int reopenWindowDays, @Min(100) long grabLockTtlMs) {
    }

    public record Attachment(
            @NotBlank String dir,
            @Min(1) long maxSizeBytes,
            @NotEmpty List<String> allowedExt) {
    }
}
