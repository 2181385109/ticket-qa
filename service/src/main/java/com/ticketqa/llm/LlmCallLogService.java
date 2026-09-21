package com.ticketqa.llm;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.ticketqa.common.TraceIdFilter;
import com.ticketqa.domain.entity.LlmCallLog;
import com.ticketqa.mapper.LlmCallLogMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * LLM 调用落盘。
 *
 * record() 用 REQUIRES_NEW:调用 LLM 这件事已经发生了,不管外层工单事务成不成功,
 * 这条记录都应该留下(它是排查"为什么分类错了 / 为什么慢"的唯一证据)。
 * REQUIRES_NEW 会挂起当前事务、另拿一个连接开新事务、提交后再恢复——所以它比默认传播贵一点。
 *
 * bindTicket() 用默认传播(REQUIRED):加入外层事务,工单插入回滚时这次绑定也回滚,
 * 不会留下指向不存在工单的 ticket_id。
 */
@Service
public class LlmCallLogService {

    private final LlmCallLogMapper mapper;

    public LlmCallLogService(LlmCallLogMapper mapper) {
        this.mapper = mapper;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW, rollbackFor = Exception.class)
    public Long record(LlmCallLog log) {
        log.setTraceId(TraceIdFilter.current());
        mapper.insert(log);
        return log.getId();
    }

    @Transactional(rollbackFor = Exception.class)
    public void bindTicket(Long callLogId, Long ticketId) {
        if (callLogId == null) {
            return;
        }
        mapper.update(null, new LambdaUpdateWrapper<LlmCallLog>()
                .eq(LlmCallLog::getId, callLogId)
                .set(LlmCallLog::getTicketId, ticketId));
    }
}
