package com.ticketqa.audit;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ticketqa.common.TraceIdFilter;
import com.ticketqa.domain.entity.TicketAuditLog;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.mapper.TicketAuditLogMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 审计日志写入。
 * propagation = MANDATORY:必须在已有事务里被调用,否则直接抛异常。
 * 这是把 ADR-002 的约束("审计与状态变更同一事务")写进代码,而不是靠口头约定。
 */
@Service
public class AuditLogService {

    private final TicketAuditLogMapper auditLogMapper;

    public AuditLogService(TicketAuditLogMapper auditLogMapper) {
        this.auditLogMapper = auditLogMapper;
    }

    @Transactional(propagation = Propagation.MANDATORY, rollbackFor = Exception.class)
    public TicketAuditLog record(Long ticketId, TicketStatus from, TicketStatus to,
                                 Long operatorId, String operatorName, AuditSource source, String remark) {
        TicketAuditLog log = new TicketAuditLog();
        log.setTicketId(ticketId);
        log.setFromStatus(from);
        log.setToStatus(to);
        log.setOperatorId(operatorId);
        log.setOperatorName(operatorName);
        log.setSource(source);
        log.setRemark(remark);
        log.setTraceId(TraceIdFilter.current());
        auditLogMapper.insert(log);
        return log;
    }

    public List<TicketAuditLog> listByTicket(Long ticketId) {
        return auditLogMapper.selectList(
                new LambdaQueryWrapper<TicketAuditLog>()
                        .eq(TicketAuditLog::getTicketId, ticketId)
                        .orderByAsc(TicketAuditLog::getId));
    }
}
