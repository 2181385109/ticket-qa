package com.ticketqa.domain.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.FieldStrategy;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.Version;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import com.ticketqa.domain.enums.TicketStatus;

import java.time.LocalDateTime;

/**
 * 工单实体,一行对应 ticket 表一条记录。
 * 没有 Lombok:getter/setter 手写,读者能看到 MyBatis-Plus 到底靠什么反射填值(ADR-010)。
 * 字段名驼峰 ↔ 列名下划线由 map-underscore-to-camel-case 自动映射。
 */
@TableName("ticket")
public class Ticket {

    @TableId(type = IdType.AUTO)
    private Long id;
    private String ticketNo;
    private String title;
    private String content;
    private TicketCategory category;
    private TicketPriority priority;
    private TicketStatus status;
    private Long customerId;
    private Long groupId;
    /** updateById 默认跳过 null 字段;退回 PENDING 要把 assignee 清空,所以这两个字段声明为 null 也写 */
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private Long assigneeId;
    private Long createdBy;
    private LocalDateTime slaDeadline;
    private LocalDateTime escalatedAt;
    @TableField(updateStrategy = FieldStrategy.ALWAYS)
    private LocalDateTime closedAt;
    /**
     * 乐观锁版本号(ADR-016 / ADR-017):OptimisticLockerInnerInterceptor 把 updateById 改写成
     * UPDATE ... SET version = old + 1 WHERE id = ? AND version = old;受影响 0 行即"读到的快照已过期"。
     * 它保证的是:凡是 updateById 成功的那一行,写之前的样子就是内存里这份快照——审计的 from_status 因此可信。
     */
    @Version
    private Integer version;
    /** 逻辑删除标记:查询自动加 deleted=0,delete 改写成 update deleted=1 */
    @TableLogic
    private Integer deleted;
    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getTicketNo() {
        return ticketNo;
    }

    public void setTicketNo(String ticketNo) {
        this.ticketNo = ticketNo;
    }

    public String getTitle() {
        return title;
    }

    public void setTitle(String title) {
        this.title = title;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public TicketCategory getCategory() {
        return category;
    }

    public void setCategory(TicketCategory category) {
        this.category = category;
    }

    public TicketPriority getPriority() {
        return priority;
    }

    public void setPriority(TicketPriority priority) {
        this.priority = priority;
    }

    public TicketStatus getStatus() {
        return status;
    }

    public void setStatus(TicketStatus status) {
        this.status = status;
    }

    public Long getCustomerId() {
        return customerId;
    }

    public void setCustomerId(Long customerId) {
        this.customerId = customerId;
    }

    public Long getGroupId() {
        return groupId;
    }

    public void setGroupId(Long groupId) {
        this.groupId = groupId;
    }

    public Long getAssigneeId() {
        return assigneeId;
    }

    public void setAssigneeId(Long assigneeId) {
        this.assigneeId = assigneeId;
    }

    public Long getCreatedBy() {
        return createdBy;
    }

    public void setCreatedBy(Long createdBy) {
        this.createdBy = createdBy;
    }

    public LocalDateTime getSlaDeadline() {
        return slaDeadline;
    }

    public void setSlaDeadline(LocalDateTime slaDeadline) {
        this.slaDeadline = slaDeadline;
    }

    public LocalDateTime getEscalatedAt() {
        return escalatedAt;
    }

    public void setEscalatedAt(LocalDateTime escalatedAt) {
        this.escalatedAt = escalatedAt;
    }

    public LocalDateTime getClosedAt() {
        return closedAt;
    }

    public void setClosedAt(LocalDateTime closedAt) {
        this.closedAt = closedAt;
    }

    public Integer getVersion() {
        return version;
    }

    public void setVersion(Integer version) {
        this.version = version;
    }

    public Integer getDeleted() {
        return deleted;
    }

    public void setDeleted(Integer deleted) {
        this.deleted = deleted;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }
}
