package com.ticketqa.domain.enums;

/**
 * 审计日志的操作来源。
 * MANUAL    人工通过接口操作
 * SCHEDULER SLA 定时任务自动升级
 * LLM       创建工单时由 LLM 路径完成自动分类 / 优先级 / SLA 截止时间的那条初始记录
 */
public enum AuditSource {
    MANUAL,
    SCHEDULER,
    LLM
}
