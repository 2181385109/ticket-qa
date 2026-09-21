package com.ticketqa.platform.perf;

import com.ticketqa.platform.common.Result;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/perf-runs")
public class PerfRunController {

    private final PerfRunService service;

    public PerfRunController(PerfRunService service) {
        this.service = service;
    }

    /** 导入一轮压测(含环境状态);同 tag 覆盖;baseline=true 直接设为该档位基线 */
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Result<PerfRun> importRun(@Valid @RequestBody ImportPerfRunRequest req) {
        return Result.ok(service.importRun(req));
    }

    @GetMapping
    public Result<List<PerfRun>> list(@RequestParam(required = false) String scenario,
                                      @RequestParam(required = false) Integer threads,
                                      @RequestParam(defaultValue = "100") int limit) {
        return Result.ok(service.list(scenario, threads, limit));
    }

    @GetMapping("/{id}")
    public Result<PerfRun> get(@PathVariable Long id) {
        return Result.ok(service.get(id));
    }

    @PutMapping("/{id}/baseline")
    public Result<PerfRun> markBaseline(@PathVariable Long id) {
        return Result.ok(service.markBaseline(id));
    }

    /** 本轮 vs 基线(不传 baselineId 就用该 scenario+threads 的当前基线) */
    @GetMapping("/{id}/compare")
    public Result<PerfComparator.Result> compare(@PathVariable Long id, @RequestParam(required = false) Long baselineId) {
        return Result.ok(service.compare(id, baselineId));
    }
}
