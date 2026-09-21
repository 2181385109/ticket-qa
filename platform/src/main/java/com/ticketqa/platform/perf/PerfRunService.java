package com.ticketqa.platform.perf;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.ticketqa.platform.common.NotFoundException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Service
public class PerfRunService {

    private final PerfRunMapper mapper;
    private final PerfComparator comparator;

    public PerfRunService(PerfRunMapper mapper, CompareProperties props) {
        this.mapper = mapper;
        this.comparator = new PerfComparator(props.qpsDropRedPct(), props.p99RiseRedPct());
    }

    /** 同 tag 重复导入视为覆盖(同一轮压测重新汇总是常态)。baseline=true 时同 scenario+threads 的旧基线自动让位。 */
    @Transactional(rollbackFor = Exception.class)
    public PerfRun importRun(ImportPerfRunRequest req) {
        PerfRun existing = mapper.selectOne(new LambdaQueryWrapper<PerfRun>().eq(PerfRun::getTag, req.tag()));
        PerfRun run = existing == null ? new PerfRun() : existing;
        run.setTag(req.tag());
        run.setScenario(req.scenario());
        run.setThreads(req.threads());
        run.setDurationS(req.durationS() == null ? 0 : req.durationS());
        run.setSamples(req.samples());
        run.setQps(req.qps());
        run.setAvgMs(req.avgMs());
        run.setP50Ms(req.p50Ms());
        run.setP95Ms(req.p95Ms());
        run.setP99Ms(req.p99Ms());
        run.setMaxMs(req.maxMs());
        run.setErrorRate(req.errorRate() == null ? BigDecimal.ZERO : req.errorRate());
        run.setCommitSha(req.commitSha());
        run.setExecutedAt(req.executedAt());
        run.setEnv(req.env());
        run.setNote(req.note());
        boolean markBaseline = Boolean.TRUE.equals(req.baseline());
        run.setBaseline(markBaseline || (existing != null && Boolean.TRUE.equals(existing.getBaseline())));
        if (existing == null) {
            run.setCreatedAt(LocalDateTime.now());
            mapper.insert(run);
        } else {
            mapper.updateById(run);
        }
        if (markBaseline) {
            markBaseline(run.getId());
        }
        return run;
    }

    /** 同 scenario + threads 只有一条基线 */
    @Transactional(rollbackFor = Exception.class)
    public PerfRun markBaseline(Long id) {
        PerfRun run = get(id);
        mapper.update(null, new LambdaUpdateWrapper<PerfRun>()
                .eq(PerfRun::getScenario, run.getScenario()).eq(PerfRun::getThreads, run.getThreads())
                .set(PerfRun::getBaseline, false));
        mapper.update(null, new LambdaUpdateWrapper<PerfRun>().eq(PerfRun::getId, id).set(PerfRun::getBaseline, true));
        return get(id);
    }

    public PerfRun get(Long id) {
        PerfRun run = mapper.selectById(id);
        if (run == null) {
            throw new NotFoundException("压测轮次不存在: " + id);
        }
        return run;
    }

    public List<PerfRun> list(String scenario, Integer threads, int limit) {
        return mapper.selectList(new LambdaQueryWrapper<PerfRun>()
                .eq(scenario != null && !scenario.isBlank(), PerfRun::getScenario, scenario)
                .eq(threads != null, PerfRun::getThreads, threads)
                .orderByDesc(PerfRun::getExecutedAt)
                .last("LIMIT " + Math.max(1, Math.min(limit, 500))));
    }

    /**
     * 本轮 vs 基线。baselineId 不给就取同 scenario+threads 里标了 baseline 的那条;都没有 → 404,
     * 不会偷偷拿"上一轮"来比——上一轮不是基线,比了也不能下结论。
     */
    public PerfComparator.Result compare(Long currentId, Long baselineId) {
        PerfRun current = get(currentId);
        PerfRun baseline;
        if (baselineId != null) {
            baseline = get(baselineId);
        } else {
            baseline = mapper.selectOne(new LambdaQueryWrapper<PerfRun>()
                    .eq(PerfRun::getScenario, current.getScenario()).eq(PerfRun::getThreads, current.getThreads())
                    .eq(PerfRun::getBaseline, true).last("LIMIT 1"));
            if (baseline == null) {
                throw new NotFoundException("scenario=" + current.getScenario() + " threads=" + current.getThreads()
                        + " 还没有基线,先 PUT /api/perf-runs/{id}/baseline 指定一条");
            }
        }
        if (!baseline.getScenario().equals(current.getScenario()) || !baseline.getThreads().equals(current.getThreads())) {
            throw new IllegalArgumentException("基线与本轮的 scenario / threads 不同,不可比");
        }
        return comparator.compare(baseline, current);
    }
}
