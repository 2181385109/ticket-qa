package com.ticketqa.platform.run;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/** 一次测试执行的汇总:批次、用例数、通过率、耗时、覆盖率。一行对应 qa_test_run 一条记录。 */
@TableName("qa_test_run")
public class TestRun {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String batchNo;
    private String suite;
    private String source;
    private String commitSha;
    private String branch;
    private LocalDateTime startedAt;
    private Long durationMs;
    private Integer total;
    private Integer passed;
    private Integer failed;
    private Integer skipped;
    private Integer xfailed;
    private BigDecimal passRate;
    private BigDecimal lineCoverage;
    private BigDecimal branchCoverage;
    private String coverageSource;
    private String note;
    private LocalDateTime createdAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getBatchNo() { return batchNo; }
    public void setBatchNo(String batchNo) { this.batchNo = batchNo; }
    public String getSuite() { return suite; }
    public void setSuite(String suite) { this.suite = suite; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public String getCommitSha() { return commitSha; }
    public void setCommitSha(String commitSha) { this.commitSha = commitSha; }
    public String getBranch() { return branch; }
    public void setBranch(String branch) { this.branch = branch; }
    public LocalDateTime getStartedAt() { return startedAt; }
    public void setStartedAt(LocalDateTime startedAt) { this.startedAt = startedAt; }
    public Long getDurationMs() { return durationMs; }
    public void setDurationMs(Long durationMs) { this.durationMs = durationMs; }
    public Integer getTotal() { return total; }
    public void setTotal(Integer total) { this.total = total; }
    public Integer getPassed() { return passed; }
    public void setPassed(Integer passed) { this.passed = passed; }
    public Integer getFailed() { return failed; }
    public void setFailed(Integer failed) { this.failed = failed; }
    public Integer getSkipped() { return skipped; }
    public void setSkipped(Integer skipped) { this.skipped = skipped; }
    public Integer getXfailed() { return xfailed; }
    public void setXfailed(Integer xfailed) { this.xfailed = xfailed; }
    public BigDecimal getPassRate() { return passRate; }
    public void setPassRate(BigDecimal passRate) { this.passRate = passRate; }
    public BigDecimal getLineCoverage() { return lineCoverage; }
    public void setLineCoverage(BigDecimal lineCoverage) { this.lineCoverage = lineCoverage; }
    public BigDecimal getBranchCoverage() { return branchCoverage; }
    public void setBranchCoverage(BigDecimal branchCoverage) { this.branchCoverage = branchCoverage; }
    public String getCoverageSource() { return coverageSource; }
    public void setCoverageSource(String coverageSource) { this.coverageSource = coverageSource; }
    public String getNote() { return note; }
    public void setNote(String note) { this.note = note; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
