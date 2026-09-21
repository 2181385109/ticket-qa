package com.ticketqa.platform.perf;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

/**
 * 压测轮次导入格式(POST /api/perf-runs)。`tests/perf/tools/to_platform.py <tag>` 能从 run_load.sh 的产物直接生成。
 * env 必填且不能为空:没有环境状态的压测数字不可比较(KI-010),平台拒收。
 */
public record ImportPerfRunRequest(
        @NotBlank @Size(max = 64) String tag,
        @NotBlank @Size(max = 32) String scenario,
        @NotNull @Min(1) Integer threads,
        @Min(0) Integer durationS,
        @NotNull @Min(1) Integer samples,
        @NotNull BigDecimal qps,
        BigDecimal avgMs,
        @Min(0) Integer p50Ms,
        @Min(0) Integer p95Ms,
        @NotNull @Min(0) Integer p99Ms,
        @Min(0) Integer maxMs,
        BigDecimal errorRate,
        @Size(max = 64) String commitSha,
        @NotNull LocalDateTime executedAt,
        @NotEmpty Map<String, Object> env,
        Boolean baseline,
        @Size(max = 500) String note) {
}
