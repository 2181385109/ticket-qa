package com.ticketqa.domain.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.LlmScene;
import com.ticketqa.domain.enums.TicketCategory;
import java.time.LocalDateTime;

/**
 * LLM 调用记录:每次调用一条,含请求/响应模型名、耗时、是否降级(CLAUDE.md §5.5)。
 */
@TableName("llm_call_log")
public class LlmCallLog {

    @TableId(type = IdType.AUTO)
    private Long id;
    private Long ticketId;
    private LlmScene scene;
    private String requestModel;
    private String responseModel;
    private Integer latencyMs;
    private Boolean degraded;
    private DegradeReason degradeReason;
    private String rawCategory;
    private TicketCategory finalCategory;
    private Boolean contractViolated;
    private String traceId;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getTicketId() {
        return ticketId;
    }

    public void setTicketId(Long ticketId) {
        this.ticketId = ticketId;
    }

    public LlmScene getScene() {
        return scene;
    }

    public void setScene(LlmScene scene) {
        this.scene = scene;
    }

    public String getRequestModel() {
        return requestModel;
    }

    public void setRequestModel(String requestModel) {
        this.requestModel = requestModel;
    }

    public String getResponseModel() {
        return responseModel;
    }

    public void setResponseModel(String responseModel) {
        this.responseModel = responseModel;
    }

    public Integer getLatencyMs() {
        return latencyMs;
    }

    public void setLatencyMs(Integer latencyMs) {
        this.latencyMs = latencyMs;
    }

    public Boolean getDegraded() {
        return degraded;
    }

    public void setDegraded(Boolean degraded) {
        this.degraded = degraded;
    }

    public DegradeReason getDegradeReason() {
        return degradeReason;
    }

    public void setDegradeReason(DegradeReason degradeReason) {
        this.degradeReason = degradeReason;
    }

    public String getRawCategory() {
        return rawCategory;
    }

    public void setRawCategory(String rawCategory) {
        this.rawCategory = rawCategory;
    }

    public TicketCategory getFinalCategory() {
        return finalCategory;
    }

    public void setFinalCategory(TicketCategory finalCategory) {
        this.finalCategory = finalCategory;
    }

    public Boolean getContractViolated() {
        return contractViolated;
    }

    public void setContractViolated(Boolean contractViolated) {
        this.contractViolated = contractViolated;
    }

    public String getTraceId() {
        return traceId;
    }

    public void setTraceId(String traceId) {
        this.traceId = traceId;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }
}
