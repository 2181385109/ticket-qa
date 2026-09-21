package com.ticketqa.platform.perf;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 基线对比的纯函数(没有 Spring、没有数据库,单测直接 new)。
 *
 * 两步:
 *  1. 指标差:QPS 下降超过阈值或 P99 上升超过阈值 → 标红;
 *  2. 环境差:按 env_state.py 的快照逐项比较池大小、堆上限、数据量、后台任务、MQ 积压、MySQL 持久化配置——
 *     任一显著不同,对比结论降级为 UNRELIABLE(黄):数字可以看,但不能据此说"退化了"。
 *     这条规则来自 KI-010:同一代码在不同池状态下 QPS / 成功数都会变,不带环境的对比是在比环境不是比代码。
 */
public final class PerfComparator {

    public record EnvDiff(String key, Object baseline, Object current, boolean significant, String why) {
    }

    public record Result(PerfRun baseline, PerfRun current,
                         BigDecimal qpsDeltaPct, BigDecimal p50DeltaPct, BigDecimal p95DeltaPct, BigDecimal p99DeltaPct,
                         boolean qpsRed, boolean p99Red, String verdict, boolean comparable,
                         List<EnvDiff> envDiffs, BigDecimal qpsDropRedPct, BigDecimal p99RiseRedPct) {
    }

    private final BigDecimal qpsDropRedPct;
    private final BigDecimal p99RiseRedPct;

    public PerfComparator(BigDecimal qpsDropRedPct, BigDecimal p99RiseRedPct) {
        this.qpsDropRedPct = qpsDropRedPct;
        this.p99RiseRedPct = p99RiseRedPct;
    }

    public Result compare(PerfRun baseline, PerfRun current) {
        BigDecimal qpsDelta = pct(baseline.getQps(), current.getQps());
        BigDecimal p50Delta = pct(baseline.getP50Ms(), current.getP50Ms());
        BigDecimal p95Delta = pct(baseline.getP95Ms(), current.getP95Ms());
        BigDecimal p99Delta = pct(baseline.getP99Ms(), current.getP99Ms());
        boolean qpsRed = qpsDelta != null && qpsDelta.compareTo(qpsDropRedPct.negate()) <= 0;
        boolean p99Red = p99Delta != null && p99Delta.compareTo(p99RiseRedPct) >= 0;
        List<EnvDiff> diffs = envDiffs(baseline.getEnv(), current.getEnv());
        boolean comparable = diffs.stream().noneMatch(EnvDiff::significant);
        String verdict = !comparable ? "UNRELIABLE" : (qpsRed || p99Red) ? "RED" : "GREEN";
        return new Result(baseline, current, qpsDelta, p50Delta, p95Delta, p99Delta, qpsRed, p99Red, verdict, comparable,
                diffs, qpsDropRedPct, p99RiseRedPct);
    }

    /** (current - baseline) / baseline * 100,保留 1 位;基线为 0 或缺失返回 null */
    static BigDecimal pct(Number baseline, Number current) {
        if (baseline == null || current == null || baseline.doubleValue() == 0) {
            return null;
        }
        double d = (current.doubleValue() - baseline.doubleValue()) / baseline.doubleValue() * 100;
        return BigDecimal.valueOf(d).setScale(1, RoundingMode.HALF_UP);
    }

    /** 逐项比较 env 快照;找不到的键记为 null 且不显著(老快照可能没有这一项) */
    static List<EnvDiff> envDiffs(Map<String, Object> base, Map<String, Object> cur) {
        List<EnvDiff> out = new ArrayList<>();
        addIfDifferent(out, "hikari.total(起跑池大小)", num(base, "hikari", "total"), num(cur, "hikari", "total"), true,
                "能同时进库的线程数 = 池大小 + 1,池不同结果不可比(KI-010)");
        addIfDifferent(out, "hikari.max", num(base, "hikari", "max"), num(cur, "hikari", "max"), true, "连接池上限是写链路的节流阀");
        addIfDifferent(out, "jvm.heap_max_mb", num(base, "jvm", "heap_max_mb"), num(cur, "jvm", "heap_max_mb"), true, "堆上限不同 GC 行为不同");
        relative(out, "mysql.ticket_rows(数据量)", num(base, "mysql", "ticket_rows"), num(cur, "mysql", "ticket_rows"), 0.2,
                "数据量相差超过 20%:索引深度 / buffer pool 命中率 / COUNT 成本都不同");
        Double bBacklog = num(base, "mysql", "sla_backlog");
        Double cBacklog = num(cur, "mysql", "sla_backlog");
        if (bBacklog != null && cBacklog != null && (bBacklog > 0 || cBacklog > 0) && !Objects.equals(bBacklog, cBacklog)) {
            out.add(new EnvDiff("mysql.sla_backlog(后台待升级)", bBacklog, cBacklog, true, "SLA 调度器在后台每 30 s 写 100 张,与压测流量争同一个连接池"));
        }
        Double bQueue = queueSum(base);
        Double cQueue = queueSum(cur);
        if (bQueue != null && cQueue != null && Math.abs(bQueue - cQueue) > 1000) {
            out.add(new EnvDiff("mq.queues(积压合计)", bQueue, cQueue, true, "消费者在追积压时会和 HTTP 请求争连接池"));
        }
        Map<String, Object> bVars = nested(base, "mysql", "mysql_vars");
        Map<String, Object> cVars = nested(cur, "mysql", "mysql_vars");
        if (bVars != null && cVars != null) {
            for (String key : new String[]{"innodb_flush_log_at_trx_commit", "sync_binlog", "transaction_isolation",
                    "innodb_buffer_pool_size", "max_connections", "slow_query_log"}) {
                addIfDifferent(out, "mysql." + key, bVars.get(key), cVars.get(key), true, "MySQL 持久化 / 日志配置决定 COMMIT 与查询成本");
            }
        }
        addIfDifferent(out, "llm.circuit_state", num(base, "llm", "circuit_state"), num(cur, "llm", "circuit_state"), true,
                "熔断打开时创建链路不调挡板,耗时结构完全不同");
        addIfDifferent(out, "git", str(base, "git"), str(cur, "git"), false, "被比较的对象本身");
        return out;
    }

    private static void addIfDifferent(List<EnvDiff> out, String key, Object b, Object c, boolean significant, String why) {
        if (b == null && c == null) {
            return;
        }
        boolean same = b != null && c != null && (b instanceof Number nb && c instanceof Number nc
                ? nb.doubleValue() == nc.doubleValue() : Objects.equals(String.valueOf(b), String.valueOf(c)));
        if (!same) {
            out.add(new EnvDiff(key, b, c, significant && b != null && c != null, why));
        }
    }

    private static void relative(List<EnvDiff> out, String key, Double b, Double c, double tolerance, String why) {
        if (b == null || c == null) {
            return;
        }
        double denominator = Math.max(Math.max(b, c), 1);
        if (Math.abs(b - c) / denominator > tolerance) {
            out.add(new EnvDiff(key, b, c, true, why));
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> nested(Map<String, Object> m, String... path) {
        Object cur = m;
        for (String p : path) {
            if (!(cur instanceof Map<?, ?> map)) {
                return null;
            }
            cur = map.get(p);
        }
        return cur instanceof Map<?, ?> map ? (Map<String, Object>) map : null;
    }

    private static Double num(Map<String, Object> m, String group, String key) {
        Map<String, Object> g = nested(m, group);
        Object v = g == null ? null : g.get(key);
        if (v instanceof Number n) {
            return n.doubleValue();
        }
        if (v instanceof String s) {
            try {
                return Double.parseDouble(s);
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private static String str(Map<String, Object> m, String key) {
        Object v = m == null ? null : m.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private static Double queueSum(Map<String, Object> m) {
        Map<String, Object> q = nested(m, "mq", "queues");
        if (q == null) {
            return null;
        }
        double sum = 0;
        for (Object v : q.values()) {
            if (v instanceof Number n) {
                sum += n.doubleValue();
            }
        }
        return sum;
    }
}
