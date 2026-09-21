package com.ticketqa.config;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * llm.* 配置。阈值(3s / 5 次 / 60s)来自 CLAUDE.md §5.5,理由见 ADR-004。
 */
@Validated
@ConfigurationProperties(prefix = "llm")
public record LlmProperties(
        @NotBlank @Pattern(regexp = "real|mock") String mode,
        @Min(100) long timeoutMs,
        @NotNull Circuit circuit,
        @NotNull Real real,
        @NotNull Mock mock) {

    public record Circuit(@Min(1) int failureThreshold, @Min(1) int openSeconds) {
    }

    public record Real(@NotBlank String baseUrl, String apiKey, @NotBlank String model) {
    }

    public record Mock(@NotBlank String baseUrl, @NotBlank String model) {
    }

    public boolean isMock() {
        return "mock".equals(mode);
    }
}
