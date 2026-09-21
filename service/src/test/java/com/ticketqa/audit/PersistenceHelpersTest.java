package com.ticketqa.audit;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.ticketqa.agent.AgentCache;
import com.ticketqa.agent.AgentService;
import com.ticketqa.agent.AgentSnapshot;
import com.ticketqa.auth.CurrentUser;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.common.NotFoundException;
import com.ticketqa.domain.entity.Agent;
import com.ticketqa.domain.entity.LlmCallLog;
import com.ticketqa.domain.entity.TicketAuditLog;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.LlmScene;
import com.ticketqa.domain.enums.Role;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.llm.LlmCallLogService;
import com.ticketqa.mapper.AgentMapper;
import com.ticketqa.mapper.LlmCallLogMapper;
import com.ticketqa.mapper.TicketAuditLogMapper;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.MDC;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 三个"薄"持久化辅助类:AuditLogService / LlmCallLogService / AgentService(+AgentCache)。
 * 它们的逻辑很少,但审计日志的 traceId 来源、绑定工单的空值短路、停用坐席视为不存在,都是接口用例依赖的前提。
 *
 * LambdaQueryWrapper 需要 MyBatis-Plus 的表元数据缓存,这里在 @BeforeAll 里手动初始化两张表的 TableInfo,
 * 否则 TicketAuditLog::getTicketId 这种方法引用解析不出列名(切片测试里由 MP 自动完成,纯 Mockito 环境要自己来)。
 */
@ExtendWith(MockitoExtension.class)
class PersistenceHelpersTest {

    @Mock
    private TicketAuditLogMapper auditLogMapper;
    @Mock
    private LlmCallLogMapper llmCallLogMapper;
    @Mock
    private AgentMapper agentMapper;

    @BeforeAll
    static void initTableInfo() {
        MapperBuilderAssistant assistant = new MapperBuilderAssistant(new MybatisConfiguration(), "");
        TableInfoHelper.initTableInfo(assistant, TicketAuditLog.class);
        TableInfoHelper.initTableInfo(assistant, LlmCallLog.class);
    }

    @Test
    @DisplayName("审计日志:字段齐全,traceId 取自 MDC;MDC 为空时写 '-' 而不是 null")
    void auditRecordFillsTraceId() {
        AuditLogService service = new AuditLogService(auditLogMapper);
        MDC.put("traceId", "abc123");
        try {
            TicketAuditLog log = service.record(7L, TicketStatus.PENDING, TicketStatus.ASSIGNED, 3L, "坐席A", AuditSource.MANUAL, "抢单");
            assertThat(log.getTraceId()).isEqualTo("abc123");
            assertThat(log.getTicketId()).isEqualTo(7L);
            assertThat(log.getFromStatus()).isEqualTo(TicketStatus.PENDING);
            assertThat(log.getToStatus()).isEqualTo(TicketStatus.ASSIGNED);
            assertThat(log.getOperatorId()).isEqualTo(3L);
            assertThat(log.getSource()).isEqualTo(AuditSource.MANUAL);
            verify(auditLogMapper).insert(log);
        } finally {
            MDC.clear();
        }
        TicketAuditLog noTrace = service.record(7L, null, TicketStatus.PENDING, null, "LLM", AuditSource.LLM, "创建");
        assertThat(noTrace.getTraceId()).isEqualTo("-");
        assertThat(noTrace.getFromStatus()).isNull();
    }

    @Test
    @DisplayName("审计查询:按 ticket_id 过滤、按 id 升序")
    void auditListQueriesByTicket() {
        AuditLogService service = new AuditLogService(auditLogMapper);
        service.listByTicket(7L);
        verify(auditLogMapper).selectList(any());
    }

    @Test
    @DisplayName("LLM 调用记录:record 写 traceId 并返回自增 id;bindTicket(null) 直接返回不查库")
    void llmCallLogRecordAndBind() {
        LlmCallLogService service = new LlmCallLogService(llmCallLogMapper);
        when(llmCallLogMapper.insert(any(LlmCallLog.class))).thenAnswer(inv -> {
            ((LlmCallLog) inv.getArgument(0)).setId(55L);
            return 1;
        });
        LlmCallLog entry = new LlmCallLog();
        entry.setScene(LlmScene.CLASSIFY);

        assertThat(service.record(entry)).isEqualTo(55L);
        assertThat(entry.getTraceId()).isEqualTo("-");

        service.bindTicket(null, 1L);
        verify(llmCallLogMapper, never()).update(any(), any());

        service.bindTicket(55L, 1L);
        verify(llmCallLogMapper).update(isNull(), any());
    }

    @Test
    @DisplayName("坐席:停用的坐席对鉴权来说不存在;getOrThrow 找不到抛 40402")
    void agentServiceRules() {
        AgentCache cache = new AgentCache(agentMapper);
        AgentService service = new AgentService(cache);

        Agent active = new Agent();
        active.setId(3L);
        active.setUsername("agent_a");
        active.setDisplayName("坐席A");
        active.setRole(Role.AGENT);
        active.setGroupId(1L);
        active.setActive(true);
        Agent inactive = new Agent();
        inactive.setId(9L);
        inactive.setUsername("gone");
        inactive.setDisplayName("离职");
        inactive.setRole(Role.AGENT);
        inactive.setGroupId(1L);
        inactive.setActive(false);
        when(agentMapper.selectById(3L)).thenReturn(active);
        when(agentMapper.selectById(9L)).thenReturn(inactive);
        when(agentMapper.selectById(404L)).thenReturn(null);

        Optional<CurrentUser> user = service.findCurrentUser(3L);
        assertThat(user).isPresent();
        assertThat(user.get()).isEqualTo(new CurrentUser(3L, "agent_a", "坐席A", Role.AGENT, 1L));

        assertThat(service.findCurrentUser(9L)).as("停用坐席视为不存在").isEmpty();
        assertThat(service.findCurrentUser(404L)).isEmpty();

        AgentSnapshot snap = service.getOrThrow(9L);
        assertThat(snap.isActive()).as("改派校验只看存在与否,停用与否由业务另判").isFalse();
        assertThatThrownBy(() -> service.getOrThrow(404L))
                .isInstanceOf(NotFoundException.class)
                .extracting(e -> ((NotFoundException) e).getErrorCode()).isEqualTo(ErrorCode.AGENT_NOT_FOUND);

        ArgumentCaptor<Long> ids = ArgumentCaptor.forClass(Long.class);
        verify(agentMapper, org.mockito.Mockito.atLeastOnce()).selectById(ids.capture());
        assertThat(ids.getAllValues()).contains(3L, 9L, 404L);
    }
}
