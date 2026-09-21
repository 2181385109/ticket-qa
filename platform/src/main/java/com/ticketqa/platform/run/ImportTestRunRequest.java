package com.ticketqa.platform.run;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 执行记录导入格式(POST /api/runs)。字段含义见 platform/README.md。
 * passRate 不让调用方传:由 passed / (total - skipped - xfailed) 算出,避免两边算法不一致。
 */
public record ImportTestRunRequest(
        @NotBlank @Size(max = 64) String batchNo,
        @NotBlank @Size(max = 32) String suite,
        @Size(max = 32) String source,
        @Size(max = 64) String commitSha,
        @Size(max = 128) String branch,
        @NotNull LocalDateTime startedAt,
        @Min(0) Long durationMs,
        @NotNull @Min(0) Integer total,
        @NotNull @Min(0) Integer passed,
        @Min(0) Integer failed,
        @Min(0) Integer skipped,
        @Min(0) Integer xfailed,
        BigDecimal lineCoverage,
        BigDecimal branchCoverage,
        @Size(max = 32) String coverageSource,
        @Size(max = 500) String note) {
}
