package com.ticketqa.platform.perf;

import jakarta.validation.constraints.DecimalMin;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.math.BigDecimal;

/** 标红阈值(ADR-022):QPS 下降 ≥ qpsDropRedPct% 或 P99 上升 ≥ p99RiseRedPct% */
@Validated
@ConfigurationProperties(prefix = "platform.compare")
public record CompareProperties(@DecimalMin("0") BigDecimal qpsDropRedPct, @DecimalMin("0") BigDecimal p99RiseRedPct) {
}
