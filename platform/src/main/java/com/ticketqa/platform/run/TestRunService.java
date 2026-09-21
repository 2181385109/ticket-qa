package com.ticketqa.platform.run;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ticketqa.platform.common.NotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.Comparator;
import java.util.List;

@Service
public class TestRunService {

    private final TestRunMapper mapper;

    public TestRunService(TestRunMapper mapper) {
        this.mapper = mapper;
    }

    /** 同一 batchNo 重复导入视为覆盖(CI 重跑同一批次是常态),不是报错。 */
    @Transactional(rollbackFor = Exception.class)
    public TestRun importRun(ImportTestRunRequest req) {
        TestRun existing = mapper.selectOne(new LambdaQueryWrapper<TestRun>().eq(TestRun::getBatchNo, req.batchNo()));
        TestRun run = existing == null ? new TestRun() : existing;
        run.setBatchNo(req.batchNo());
        run.setSuite(req.suite());
        run.setSource(req.source() == null ? "local" : req.source());
        run.setCommitSha(req.commitSha());
        run.setBranch(req.branch());
        run.setStartedAt(req.startedAt());
        run.setDurationMs(req.durationMs() == null ? 0L : req.durationMs());
        run.setTotal(req.total());
        run.setPassed(req.passed());
        run.setFailed(nz(req.failed()));
        run.setSkipped(nz(req.skipped()));
        run.setXfailed(nz(req.xfailed()));
        run.setPassRate(passRate(req.total(), req.passed(), nz(req.skipped()), nz(req.xfailed())));
        run.setLineCoverage(req.lineCoverage());
        run.setBranchCoverage(req.branchCoverage());
        run.setCoverageSource(req.coverageSource());
        run.setNote(req.note());
        if (existing == null) {
            run.setCreatedAt(LocalDateTime.now());
            mapper.insert(run);
        } else {
            mapper.updateById(run);
        }
        return run;
    }

    /** 通过率的分母去掉 skipped 和 xfailed:它们既不是通过也不是失败,算进去会让"全绿"的批次显示 98%。 */
    static BigDecimal passRate(int total, int passed, int skipped, int xfailed) {
        int denominator = total - skipped - xfailed;
        if (denominator <= 0) {
            return BigDecimal.ZERO;
        }
        return BigDecimal.valueOf(passed * 100.0 / denominator).setScale(2, RoundingMode.HALF_UP);
    }

    public List<TestRun> list(String suite, int limit) {
        return mapper.selectList(new LambdaQueryWrapper<TestRun>()
                .eq(suite != null && !suite.isBlank(), TestRun::getSuite, suite)
                .orderByDesc(TestRun::getStartedAt)
                .last("LIMIT " + Math.max(1, Math.min(limit, 500))));
    }

    public TestRun get(Long id) {
        TestRun run = mapper.selectById(id);
        if (run == null) {
            throw new NotFoundException("执行记录不存在: " + id);
        }
        return run;
    }

    /** 按时间升序的趋势点 */
    public List<TrendPoint> trend(String suite, int limit) {
        return list(suite, limit).stream()
                .sorted(Comparator.comparing(TestRun::getStartedAt))
                .map(r -> new TrendPoint(r.getId(), r.getBatchNo(), r.getSuite(), r.getSource(), r.getStartedAt(),
                        r.getPassRate(), r.getLineCoverage(), r.getBranchCoverage(), r.getTotal(), r.getFailed()))
                .toList();
    }

    private static int nz(Integer v) {
        return v == null ? 0 : v;
    }
}
