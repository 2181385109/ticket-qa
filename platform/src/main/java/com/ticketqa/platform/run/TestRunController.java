package com.ticketqa.platform.run;

import com.ticketqa.platform.common.Result;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/runs")
public class TestRunController {

    private final TestRunService service;

    public TestRunController(TestRunService service) {
        this.service = service;
    }

    /** 导入一条执行记录;同 batchNo 覆盖 */
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Result<TestRun> importRun(@Valid @RequestBody ImportTestRunRequest req) {
        return Result.ok(service.importRun(req));
    }

    @GetMapping
    public Result<List<TestRun>> list(@RequestParam(required = false) String suite,
                                      @RequestParam(defaultValue = "50") int limit) {
        return Result.ok(service.list(suite, limit));
    }

    @GetMapping("/trend")
    public Result<List<TrendPoint>> trend(@RequestParam(required = false) String suite,
                                          @RequestParam(defaultValue = "50") int limit) {
        return Result.ok(service.trend(suite, limit));
    }

    @GetMapping("/{id}")
    public Result<TestRun> get(@PathVariable Long id) {
        return Result.ok(service.get(id));
    }
}
