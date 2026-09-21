package com.ticketqa.platform.perf;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 基线对比的判定表(ADR-022):
 *
 *   环境一致? | QPS 变化   | P99 变化  | 结论
 *   是         | −9%        | +19%      | GREEN(都在阈值内)
 *   是         | −10%       | 任意      | RED(QPS 下降触线,闭区间)
 *   是         | 任意       | +20%      | RED(P99 上升触线,闭区间)
 *   否         | −50%       | +300%     | UNRELIABLE(数字再难看也不能说退化,先解释环境)
 */
class PerfComparatorTest {

    private final PerfComparator comparator = new PerfComparator(new BigDecimal("10"), new BigDecimal("20"));

    private static Map<String, Object> env(double poolTotal, double ticketRows, double slaBacklog, double queueSum, String flush) {
        Map<String, Object> hikari = new HashMap<>(Map.of("total", poolTotal, "max", 20.0));
        Map<String, Object> mysql = new LinkedHashMap<>();
        mysql.put("ticket_rows", ticketRows);
        mysql.put("sla_backlog", slaBacklog);
        mysql.put("mysql_vars", new HashMap<>(Map.of("innodb_flush_log_at_trx_commit", flush, "sync_binlog", "1")));
        Map<String, Object> mq = new HashMap<>(Map.of("queues", new HashMap<>(Map.of("q.a", queueSum))));
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("git", "abc");
        m.put("hikari", hikari);
        m.put("jvm", new HashMap<>(Map.of("heap_max_mb", 1024.0)));
        m.put("mysql", mysql);
        m.put("mq", mq);
        m.put("llm", new HashMap<>(Map.of("circuit_state", 0.0)));
        return m;
    }

    private static PerfRun run(double qps, int p50, int p95, int p99, Map<String, Object> env) {
        PerfRun r = new PerfRun();
        r.setScenario("grab");
        r.setThreads(50);
        r.setQps(BigDecimal.valueOf(qps));
        r.setP50Ms(p50);
        r.setP95Ms(p95);
        r.setP99Ms(p99);
        r.setEnv(env);
        return r;
    }

    @Test
    @DisplayName("环境一致、QPS −9%、P99 +19%:GREEN,差值按 (cur-base)/base 算")
    void withinThresholdsIsGreen() {
        PerfRun base = run(500, 90, 110, 120, env(20, 87000, 0, 0, "1"));
        PerfRun cur = run(455, 92, 115, 142, env(20, 87000, 0, 0, "1"));
        PerfComparator.Result r = comparator.compare(base, cur);
        assertThat(r.verdict()).isEqualTo("GREEN");
        assertThat(r.comparable()).isTrue();
        assertThat(r.qpsDeltaPct()).isEqualByComparingTo("-9.0");
        assertThat(r.p99DeltaPct()).isEqualByComparingTo("18.3");
        assertThat(r.qpsRed()).isFalse();
        assertThat(r.p99Red()).isFalse();
        assertThat(r.envDiffs()).isEmpty();
    }

    @Test
    @DisplayName("QPS 恰好下降 10%:RED(阈值闭区间,和 SLA 闭区间的约定一致)")
    void qpsDropExactlyAtThresholdIsRed() {
        PerfRun base = run(500, 90, 110, 120, env(20, 87000, 0, 0, "1"));
        PerfRun cur = run(450, 90, 110, 120, env(20, 87000, 0, 0, "1"));
        PerfComparator.Result r = comparator.compare(base, cur);
        assertThat(r.qpsRed()).isTrue();
        assertThat(r.verdict()).isEqualTo("RED");
    }

    @Test
    @DisplayName("P99 恰好上升 20%:RED")
    void p99RiseExactlyAtThresholdIsRed() {
        PerfRun base = run(500, 90, 110, 100, env(20, 87000, 0, 0, "1"));
        PerfRun cur = run(500, 90, 110, 120, env(20, 87000, 0, 0, "1"));
        PerfComparator.Result r = comparator.compare(base, cur);
        assertThat(r.p99Red()).isTrue();
        assertThat(r.verdict()).isEqualTo("RED");
    }

    @Test
    @DisplayName("起跑池 3 vs 20:UNRELIABLE——即使 QPS 掉一半也不下退化结论,差异项写明原因")
    void differentPoolSizeMakesComparisonUnreliable() {
        PerfRun base = run(500, 90, 110, 120, env(20, 87000, 0, 0, "1"));
        PerfRun cur = run(250, 200, 300, 480, env(3, 87000, 0, 0, "1"));
        PerfComparator.Result r = comparator.compare(base, cur);
        assertThat(r.comparable()).isFalse();
        assertThat(r.verdict()).isEqualTo("UNRELIABLE");
        assertThat(r.qpsRed()).as("指标差仍然算出来,只是结论降级").isTrue();
        assertThat(r.envDiffs()).anySatisfy(d -> {
            assertThat(d.key()).startsWith("hikari.total");
            assertThat(d.significant()).isTrue();
            assertThat(d.why()).contains("KI-010");
        });
    }

    @Test
    @DisplayName("数据量 10 万 vs 12 万(20%)不显著;10 万 vs 13 万(30%)显著;后台 SLA 积压一方 > 0 显著;MQ 积压差 > 1000 显著;flush 配置不同显著")
    void environmentRules() {
        Map<String, Object> base = env(20, 100000, 0, 0, "1");
        assertThat(PerfComparator.envDiffs(base, env(20, 120000, 0, 0, "1"))).noneMatch(PerfComparator.EnvDiff::significant);
        assertThat(PerfComparator.envDiffs(base, env(20, 130000, 0, 0, "1"))).anyMatch(d -> d.key().startsWith("mysql.ticket_rows") && d.significant());
        assertThat(PerfComparator.envDiffs(base, env(20, 100000, 3907, 0, "1"))).anyMatch(d -> d.key().startsWith("mysql.sla_backlog") && d.significant());
        assertThat(PerfComparator.envDiffs(base, env(20, 100000, 0, 50000, "1"))).anyMatch(d -> d.key().startsWith("mq.queues") && d.significant());
        assertThat(PerfComparator.envDiffs(base, env(20, 100000, 0, 0, "2"))).anyMatch(d -> d.key().equals("mysql.innodb_flush_log_at_trx_commit") && d.significant());
    }

    @Test
    @DisplayName("git 不同只记录不判显著(它就是被比较的对象);老快照缺某一项时记为 null、不显著、不报错")
    void gitIsInformationalAndMissingKeysAreTolerated() {
        Map<String, Object> base = env(20, 100000, 0, 0, "1");
        Map<String, Object> cur = env(20, 100000, 0, 0, "1");
        cur.put("git", "def");
        cur.remove("llm");
        var diffs = PerfComparator.envDiffs(base, cur);
        assertThat(diffs).noneMatch(PerfComparator.EnvDiff::significant);
        assertThat(diffs).extracting(PerfComparator.EnvDiff::key).containsExactlyInAnyOrder("llm.circuit_state", "git");
        assertThat(diffs).filteredOn(d -> d.key().equals("llm.circuit_state")).singleElement().satisfies(d -> assertThat(d.current()).isNull());
    }

    @Test
    @DisplayName("基线 QPS 为 0 或缺失:差值为 null,不除零")
    void zeroBaselineGivesNullDelta() {
        assertThat(PerfComparator.pct(0, 100)).isNull();
        assertThat(PerfComparator.pct(null, 100)).isNull();
        assertThat(PerfComparator.pct(200, 100)).isEqualByComparingTo("-50.0");
    }
}
