package com.ticketqa.sla;

import com.ticketqa.audit.AuditLogService;
import com.ticketqa.common.TraceIdFilter;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.mapper.TicketMapper;
import com.ticketqa.ticket.event.TicketDomainEvent;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;

/**
 * 单张工单的升级动作(ADR-006)。
 *
 * 防重复触发靠一条条件 UPDATE:
 *   UPDATE ticket SET status='ESCALATED', escalated_at=now, version=version+1
 *    WHERE id=? AND status=? AND status IN ('PENDING','ASSIGNED') AND version=? AND escalated_at IS NULL
 * 受影响行数为 0 就说明别人已经处理过(另一个实例、上一轮扫描、或人工刚好流转走了),直接放弃。
 * 审计和事件只在受影响行数为 1 时写——它们和这条 UPDATE 在同一个事务里。
 * status=? 和 version=? 是 ADR-017 加的:SELECT 读到 PENDING、UPDATE 前被人抢成 ASSIGNED 的话,
 * 第一版会升级成功却把审计记成 PENDING→ESCALATED;现在这种情况影响 0 行,留给下一轮扫描重新读。
 *
 * escalated_at 一旦写上就永不清空:被升级过的工单即使之后回到 ASSIGNED,也不会被第二次自动升级。
 */
@Service
public class SlaEscalationService {

    private static final Logger log = LoggerFactory.getLogger(SlaEscalationService.class);

    private final TicketMapper ticketMapper;
    private final AuditLogService auditLogService;
    private final ApplicationEventPublisher events;
    private final Counter escalatedCounter;
    private final Counter skippedCounter;

    public SlaEscalationService(TicketMapper ticketMapper, AuditLogService auditLogService,
                                ApplicationEventPublisher events, MeterRegistry registry) {
        this.ticketMapper = ticketMapper;
        this.auditLogService = auditLogService;
        this.events = events;
        this.escalatedCounter = Counter.builder("sla_escalated_total")
                .description("被 SLA 扫描自动升级的工单数").register(registry);
        this.skippedCounter = Counter.builder("sla_escalation_skipped_total")
                .description("扫描命中但条件更新影响 0 行(已被处理)的次数").register(registry);
    }

    /**
     * 每张工单一个独立事务:一张失败不影响同批其他工单。
     *
     * @return 是否真的升级了
     */
    @Transactional(rollbackFor = Exception.class)
    public boolean escalate(Long ticketId, LocalDateTime now) {
        Ticket before = ticketMapper.selectById(ticketId);
        if (before == null) {
            return false;
        }
        TicketStatus from = before.getStatus();
        int affected = ticketMapper.escalateIfStillUnresponded(ticketId, from.name(), before.getVersion(), now);
        if (affected == 0) {
            skippedCounter.increment();
            log.info("SLA 升级跳过(已被处理) ticketId={} status={}", ticketId, from);
            return false;
        }
        auditLogService.record(ticketId, from, TicketStatus.ESCALATED, null, "SCHEDULER", AuditSource.SCHEDULER,
                "超过响应时限自动升级,deadline=" + before.getSlaDeadline() + " now=" + now);
        TicketDomainEvent base = new TicketDomainEvent(EventType.STATUS_CHANGED, ticketId, before.getTicketNo(),
                from, TicketStatus.ESCALATED, before.getAssigneeId(), null, "SCHEDULER", AuditSource.SCHEDULER,
                TraceIdFilter.current(), now);
        events.publishEvent(base);
        events.publishEvent(new TicketDomainEvent(EventType.SLA_ESCALATED, ticketId, before.getTicketNo(),
                from, TicketStatus.ESCALATED, before.getAssigneeId(), null, "SCHEDULER", AuditSource.SCHEDULER,
                TraceIdFilter.current(), now));
        escalatedCounter.increment();
        log.warn("SLA 自动升级 ticketId={} no={} {} -> ESCALATED deadline={}", ticketId, before.getTicketNo(), from, before.getSlaDeadline());
        return true;
    }
}
