package com.ticketqa.platform.perf;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.extension.handlers.JacksonTypeHandler;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

/**
 * 一轮压测:JMeter 汇总 + 压测前的环境状态快照。
 * env 是 JSON 列,用 JacksonTypeHandler 在 Map 和 JSON 字符串之间转换——
 * 基线必须连同环境状态一起存(ADR-022 / KI-010),否则对比本身不可信。
 */
@TableName(value = "qa_perf_run", autoResultMap = true)
public class PerfRun {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String tag;
    private String scenario;
    private Integer threads;
    private Integer durationS;
    private Integer samples;
    private BigDecimal qps;
    private BigDecimal avgMs;
    private Integer p50Ms;
    private Integer p95Ms;
    private Integer p99Ms;
    private Integer maxMs;
    private BigDecimal errorRate;
    private String commitSha;
    private LocalDateTime executedAt;
    @TableField(value = "env_json", typeHandler = JacksonTypeHandler.class)
    private Map<String, Object> env;
    private Boolean baseline;
    private String note;
    private LocalDateTime createdAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getTag() { return tag; }
    public void setTag(String tag) { this.tag = tag; }
    public String getScenario() { return scenario; }
    public void setScenario(String scenario) { this.scenario = scenario; }
    public Integer getThreads() { return threads; }
    public void setThreads(Integer threads) { this.threads = threads; }
    public Integer getDurationS() { return durationS; }
    public void setDurationS(Integer durationS) { this.durationS = durationS; }
    public Integer getSamples() { return samples; }
    public void setSamples(Integer samples) { this.samples = samples; }
    public BigDecimal getQps() { return qps; }
    public void setQps(BigDecimal qps) { this.qps = qps; }
    public BigDecimal getAvgMs() { return avgMs; }
    public void setAvgMs(BigDecimal avgMs) { this.avgMs = avgMs; }
    public Integer getP50Ms() { return p50Ms; }
    public void setP50Ms(Integer p50Ms) { this.p50Ms = p50Ms; }
    public Integer getP95Ms() { return p95Ms; }
    public void setP95Ms(Integer p95Ms) { this.p95Ms = p95Ms; }
    public Integer getP99Ms() { return p99Ms; }
    public void setP99Ms(Integer p99Ms) { this.p99Ms = p99Ms; }
    public Integer getMaxMs() { return maxMs; }
    public void setMaxMs(Integer maxMs) { this.maxMs = maxMs; }
    public BigDecimal getErrorRate() { return errorRate; }
    public void setErrorRate(BigDecimal errorRate) { this.errorRate = errorRate; }
    public String getCommitSha() { return commitSha; }
    public void setCommitSha(String commitSha) { this.commitSha = commitSha; }
    public LocalDateTime getExecutedAt() { return executedAt; }
    public void setExecutedAt(LocalDateTime executedAt) { this.executedAt = executedAt; }
    public Map<String, Object> getEnv() { return env; }
    public void setEnv(Map<String, Object> env) { this.env = env; }
    public Boolean getBaseline() { return baseline; }
    public void setBaseline(Boolean baseline) { this.baseline = baseline; }
    public String getNote() { return note; }
    public void setNote(String note) { this.note = note; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
