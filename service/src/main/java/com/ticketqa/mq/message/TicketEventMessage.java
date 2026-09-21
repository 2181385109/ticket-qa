package com.ticketqa.mq.message;

import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.ticket.event.TicketDomainEvent;

import java.time.LocalDateTime;
import java.util.UUID;

/**
 * 发到 RabbitMQ 的消息体(JSON)。
 * messageId 由生产端生成、全局唯一,是消费端去重表的主键依据(ADR-003)。
 * 普通类 + 无参构造:Jackson 消息转换器反序列化时需要。
 */
public class TicketEventMessage {

    private String messageId;
    private EventType eventType;
    private Long ticketId;
    private String ticketNo;
    private TicketStatus fromStatus;
    private TicketStatus toStatus;
    private Long assigneeId;
    private Long operatorId;
    private String operatorName;
    private AuditSource source;
    private String traceId;
    private LocalDateTime occurredAt;

    public TicketEventMessage() {
    }

    public static TicketEventMessage from(TicketDomainEvent e) {
        TicketEventMessage m = new TicketEventMessage();
        m.messageId = UUID.randomUUID().toString();
        m.eventType = e.type();
        m.ticketId = e.ticketId();
        m.ticketNo = e.ticketNo();
        m.fromStatus = e.fromStatus();
        m.toStatus = e.toStatus();
        m.assigneeId = e.assigneeId();
        m.operatorId = e.operatorId();
        m.operatorName = e.operatorName();
        m.source = e.source();
        m.traceId = e.traceId();
        m.occurredAt = e.occurredAt();
        return m;
    }

    public String getMessageId() {
        return messageId;
    }

    public void setMessageId(String messageId) {
        this.messageId = messageId;
    }

    public EventType getEventType() {
        return eventType;
    }

    public void setEventType(EventType eventType) {
        this.eventType = eventType;
    }

    public Long getTicketId() {
        return ticketId;
    }

    public void setTicketId(Long ticketId) {
        this.ticketId = ticketId;
    }

    public String getTicketNo() {
        return ticketNo;
    }

    public void setTicketNo(String ticketNo) {
        this.ticketNo = ticketNo;
    }

    public TicketStatus getFromStatus() {
        return fromStatus;
    }

    public void setFromStatus(TicketStatus fromStatus) {
        this.fromStatus = fromStatus;
    }

    public TicketStatus getToStatus() {
        return toStatus;
    }

    public void setToStatus(TicketStatus toStatus) {
        this.toStatus = toStatus;
    }

    public Long getAssigneeId() {
        return assigneeId;
    }

    public void setAssigneeId(Long assigneeId) {
        this.assigneeId = assigneeId;
    }

    public Long getOperatorId() {
        return operatorId;
    }

    public void setOperatorId(Long operatorId) {
        this.operatorId = operatorId;
    }

    public String getOperatorName() {
        return operatorName;
    }

    public void setOperatorName(String operatorName) {
        this.operatorName = operatorName;
    }

    public AuditSource getSource() {
        return source;
    }

    public void setSource(AuditSource source) {
        this.source = source;
    }

    public String getTraceId() {
        return traceId;
    }

    public void setTraceId(String traceId) {
        this.traceId = traceId;
    }

    public LocalDateTime getOccurredAt() {
        return occurredAt;
    }

    public void setOccurredAt(LocalDateTime occurredAt) {
        this.occurredAt = occurredAt;
    }

    @Override
    public String toString() {
        return "TicketEventMessage{" + "messageId='" + messageId + '\'' + ", eventType=" + eventType
                + ", ticketId=" + ticketId + ", from=" + fromStatus + ", to=" + toStatus
                + ", assigneeId=" + assigneeId + ", source=" + source + ", traceId='" + traceId + '\'' + '}';
    }
}
