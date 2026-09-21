package com.ticketqa.platform.run;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/** 趋势图的一个点 */
public record TrendPoint(Long id, String batchNo, String suite, String source, LocalDateTime startedAt,
                         BigDecimal passRate, BigDecimal lineCoverage, BigDecimal branchCoverage,
                         Integer total, Integer failed) {
}
