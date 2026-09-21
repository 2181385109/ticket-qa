package com.ticketqa.ticket;

import com.ticketqa.agent.AgentService;
import com.ticketqa.agent.AgentSnapshot;
import com.ticketqa.audit.AuditLogService;
import com.ticketqa.auth.AccessChecker;
import com.ticketqa.auth.CurrentUser;
import com.ticketqa.auth.UserContext;
import com.ticketqa.common.AccessDeniedException;
import com.ticketqa.common.BizException;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.common.IllegalTransitionException;
import com.ticketqa.common.NotFoundException;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.Role;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.llm.DraftOutcome;
import com.ticketqa.llm.LlmCallLogService;
import com.ticketqa.llm.LlmService;
import com.ticketqa.mapper.TicketMapper;
import com.ticketqa.statemachine.TicketStateMachine;
import com.ticketqa.statemachine.TransitionTable;
import com.ticketqa.support.TestFixtures;
import com.ticketqa.ticket.dto.AssignRequest;
import com.ticketqa.ticket.dto.ReplyDraftVO;
import com.ticketqa.ticket.dto.TicketVO;
import com.ticketqa.ticket.dto.TransitionRequest;
import com.ticketqa.ticket.dto.UpdateTicketRequest;
import com.ticketqa.ticket.event.TicketDomainEvent;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.List;
import java.util.Optional;

import static com.ticketqa.domain.enums.TicketStatus.ASSIGNED;
import static com.ticketqa.domain.enums.TicketStatus.CLOSED;
import static com.ticketqa.domain.enums.TicketStatus.ESCALATED;
import static com.ticketqa.domain.enums.TicketStatus.PENDING;
import static com.ticketqa.domain.enums.TicketStatus.PROCESSING;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 工单服务:权限 → 状态机 → 落库 → 审计 → 事件 的编排是否正确。
 *
 * Mock 的是 Mapper(DB)、AgentService(坐席表)、LlmService、事件发布器、GrabLock(Redis);
 * AccessChecker、TransitionTable、TicketStateMachine 用真实对象——它们没有外部依赖,Mock 掉反而测不到编排。
 *
 * 场景法:每个接口挑"正常路径 + 每个拒绝分支各一条",拒绝分支断言"没有落库、没有审计"。
 * 并发相关(ADR-016 / ADR-017)在单测里只能模拟"UPDATE 影响 0 行"这个结果:
 * 真正的两个线程撞行锁在 tests/api/test_concurrency.py 和 tests/perf/grab_race.jmx 里测。
 */
@ExtendWith(MockitoExtension.class)
class TicketServiceTest {

    @Mock
    private TicketMapper ticketMapper;
    @Mock
    private AuditLogService auditLogService;
    @Mock
    private AgentService agentService;
    @Mock
    private LlmService llmService;
    @Mock
    private LlmCallLogService llmCallLogService;
    @Mock
    private ApplicationEventPublisher events;
    @Mock
    private TransactionTemplate txTemplate;
    @Mock
    private GrabLock grabLock;

    private SimpleMeterRegistry registry;
    private TicketService service;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        service = new TicketService(ticketMapper, new TicketStateMachine(new TransitionTable(TestFixtures.appProperties())),
                new AccessChecker(), auditLogService, agentService, llmService, llmCallLogService, events, txTemplate,
                TestFixtures.appProperties(), TestFixtures.fixedClock(), grabLock, new TicketNoGenerator(), registry);
        // 编程式事务在单测里直接执行回调(没有真事务);grab 走的就是 txTemplate
        lenient().when(txTemplate.execute(any())).thenAnswer(inv -> ((TransactionCallback<?>) inv.getArgument(0)).doInTransaction(null));
        // 乐观锁:updateById 默认视为命中 1 行;要模拟冲突的用例自己覆盖成 0
        lenient().when(ticketMapper.updateById(any(Ticket.class))).thenReturn(1);
        // Redis 前置锁默认拿到;要模拟被占 / 不可用的用例自己覆盖
        lenient().when(grabLock.tryAcquire(anyLong())).thenReturn(Optional.of("token"));
    }

    private double counter(String name) {
        return registry.find(name).counter() == null ? 0 : registry.find(name).counter().count();
    }

    @AfterEach
    void tearDown() {
        UserContext.clear();
    }

    private void loginAs(CurrentUser user) {
        UserContext.set(user);
    }

    private Ticket stored(Long id, TicketStatus status, Long groupId, Long assigneeId) {
        Ticket t = TestFixtures.ticket(id, status, groupId, assigneeId);
        t.setVersion(0);
        when(ticketMapper.selectById(id)).thenReturn(t);
        return t;
    }

    private void agentExists(Long id, Long groupId) {
        AgentSnapshot s = new AgentSnapshot();
        s.setId(id);
        s.setGroupId(groupId);
        s.setRole(Role.AGENT);
        s.setActive(true);
        when(agentService.getOrThrow(id)).thenReturn(s);
    }

    private List<TicketDomainEvent> publishedEvents() {
        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(events, org.mockito.Mockito.atLeast(0)).publishEvent(captor.capture());
        return captor.getAllValues().stream().map(TicketDomainEvent.class::cast).toList();
    }

    private void assertNothingPersisted() {
        verify(ticketMapper, never()).updateById(any(Ticket.class));
        verify(ticketMapper, never()).grabIfPending(anyLong(), anyLong(), any(), any());
        assertNoAuditNoEvent();
    }

    private void assertNoAuditNoEvent() {
        verify(auditLogService, never()).record(anyLong(), any(), any(), any(), anyString(), any(), any());
        verify(events, never()).publishEvent(any(Object.class));
    }

    // ------------------------------------------------------------------ 流转

    @Nested
    @DisplayName("transit:通用状态流转")
    class Transit {

        @Test
        @DisplayName("ASSIGNED -> PROCESSING(坐席本人):落库 + 审计 MANUAL + 一条 STATUS_CHANGED 事件")
        void legalTransitionByOwner() {
            loginAs(TestFixtures.agentA());
            Ticket t = stored(1L, ASSIGNED, 1L, 3L);

            TicketVO vo = service.transit(1L, new TransitionRequest(PROCESSING, null, "开始处理"));

            assertThat(vo.status()).isEqualTo(PROCESSING);
            verify(ticketMapper).updateById(t);
            verify(auditLogService).record(eq(1L), eq(ASSIGNED), eq(PROCESSING), eq(3L), eq("坐席A"),
                    eq(AuditSource.MANUAL), eq("开始处理"));
            List<TicketDomainEvent> evts = publishedEvents();
            assertThat(evts).extracting(TicketDomainEvent::type).containsExactly(EventType.STATUS_CHANGED);
            assertThat(evts.get(0).occurredAt()).isEqualTo(TestFixtures.NOW);
            assertThat(evts.get(0).operatorId()).isEqualTo(3L);
        }

        @Test
        @DisplayName("ASSIGNED -> CLOSED 非法:抛 IllegalTransitionException,不落库不审计不发事件")
        void illegalTransitionPersistsNothing() {
            loginAs(TestFixtures.agentA());
            Ticket t = stored(1L, ASSIGNED, 1L, 3L);

            assertThatThrownBy(() -> service.transit(1L, new TransitionRequest(CLOSED, null, null)))
                    .isInstanceOf(IllegalTransitionException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.ILLEGAL_TRANSITION);

            assertThat(t.getStatus()).isEqualTo(ASSIGNED);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("组长把 PENDING 单流转到 ASSIGNED:必须带 assigneeId,发 STATUS_CHANGED + ASSIGNED 两条事件")
        void leaderAssignsViaTransition() {
            loginAs(TestFixtures.leader1());
            stored(1L, PENDING, 1L, null);
            agentExists(4L, 1L);

            TicketVO vo = service.transit(1L, new TransitionRequest(ASSIGNED, 4L, null));

            assertThat(vo.status()).isEqualTo(ASSIGNED);
            assertThat(vo.assigneeId()).isEqualTo(4L);
            assertThat(publishedEvents()).extracting(TicketDomainEvent::type)
                    .containsExactly(EventType.STATUS_CHANGED, EventType.ASSIGNED);
        }

        @Test
        @DisplayName("流转到 ASSIGNED 没带 assigneeId → 40002")
        void assignWithoutAssigneeRejected() {
            loginAs(TestFixtures.leader1());
            stored(1L, PENDING, 1L, null);

            assertThatThrownBy(() -> service.transit(1L, new TransitionRequest(ASSIGNED, null, null)))
                    .isInstanceOf(BizException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.ASSIGNEE_REQUIRED);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("流转到 ASSIGNED 指定了别组的坐席 → 40003")
        void assignToOtherGroupRejected() {
            loginAs(TestFixtures.leader1());
            stored(1L, PENDING, 1L, null);
            agentExists(6L, 2L);

            assertThatThrownBy(() -> service.transit(1L, new TransitionRequest(ASSIGNED, 6L, null)))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.ASSIGNEE_GROUP_MISMATCH);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("坐席退回 PENDING:assignee 被进入动作清空,updateById 时该字段必须写 null")
        void agentReturnsTicketToPending() {
            loginAs(TestFixtures.agentA());
            Ticket t = stored(1L, ASSIGNED, 1L, 3L);

            TicketVO vo = service.transit(1L, new TransitionRequest(PENDING, null, "退回"));

            assertThat(vo.status()).isEqualTo(PENDING);
            assertThat(vo.assigneeId()).isNull();
            assertThat(t.getAssigneeId()).isNull();
            verify(ticketMapper).updateById(t);
        }

        @Test
        @DisplayName("AGENT 对自己的单流转到 ASSIGNED → 40302(需要 LEADER/ADMIN)")
        void agentTransitionToAssignedIsVerticalEscalation() {
            loginAs(TestFixtures.agentA());
            stored(1L, ESCALATED, 1L, 3L);

            assertThatThrownBy(() -> service.transit(1L, new TransitionRequest(ASSIGNED, 3L, null)))
                    .isInstanceOf(AccessDeniedException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.ROLE_FORBIDDEN);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("别人的单 → 40301 水平越权,连状态机都不会跑")
        void othersTicketIsHorizontalEscalation() {
            loginAs(TestFixtures.agentB());
            stored(1L, ASSIGNED, 1L, 3L);

            assertThatThrownBy(() -> service.transit(1L, new TransitionRequest(PROCESSING, null, null)))
                    .isInstanceOf(AccessDeniedException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.FORBIDDEN);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("工单不存在 → 40401")
        void notFound() {
            loginAs(TestFixtures.admin());
            when(ticketMapper.selectById(404L)).thenReturn(null);
            assertThatThrownBy(() -> service.transit(404L, new TransitionRequest(PROCESSING, null, null)))
                    .isInstanceOf(NotFoundException.class);
        }

        @Test
        @DisplayName("乐观锁冲突(updateById 影响 0 行)→ 40903,不写审计不发事件,ticket_version_conflict_total +1(ADR-017)")
        void versionConflictPersistsNoAudit() {
            loginAs(TestFixtures.agentA());
            stored(1L, ASSIGNED, 1L, 3L);
            when(ticketMapper.updateById(any(Ticket.class))).thenReturn(0);

            assertThatThrownBy(() -> service.transit(1L, new TransitionRequest(PROCESSING, null, null)))
                    .isInstanceOf(BizException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.CONCURRENT_MODIFICATION);

            assertNoAuditNoEvent();
            assertThat(counter("ticket_version_conflict_total")).isEqualTo(1);
        }
    }

    // ------------------------------------------------------------------ 抢单

    @Nested
    @DisplayName("grab:坐席抢单(ADR-016 三层:Redis 前置锁 → 条件 UPDATE → version)")
    class Grab {

        @Test
        @DisplayName("PENDING 单被本组坐席抢到:条件更新带 version、ASSIGNED、assignee=自己、审计 from=PENDING 备注「抢单」、两条事件、锁释放")
        void grabPending() {
            loginAs(TestFixtures.agentA());
            Ticket t = stored(1L, PENDING, 1L, null);
            t.setVersion(4);
            when(ticketMapper.grabIfPending(1L, 3L, 4, TestFixtures.NOW)).thenReturn(1);

            TicketVO vo = service.grab(1L);

            assertThat(vo.status()).isEqualTo(ASSIGNED);
            assertThat(vo.assigneeId()).isEqualTo(3L);
            assertThat(vo.version()).as("内存快照跟着 UPDATE 递增,返回给客户端的是新版本").isEqualTo(5);
            verify(ticketMapper, never()).updateById(any(Ticket.class));
            verify(auditLogService).record(eq(1L), eq(PENDING), eq(ASSIGNED), eq(3L), eq("坐席A"),
                    eq(AuditSource.MANUAL), eq("抢单"));
            assertThat(publishedEvents()).extracting(TicketDomainEvent::type)
                    .containsExactly(EventType.STATUS_CHANGED, EventType.ASSIGNED);
            verify(grabLock).release(1L, "token");
        }

        @Test
        @DisplayName("条件更新影响 0 行(并发下被别人先抢):40901、不写审计不发事件、grab_conflict_total +1、锁仍释放")
        void conditionalUpdateMissIsConflict() {
            loginAs(TestFixtures.agentA());
            stored(1L, PENDING, 1L, null);
            when(ticketMapper.grabIfPending(anyLong(), anyLong(), any(), any())).thenReturn(0);

            assertThatThrownBy(() -> service.grab(1L))
                    .isInstanceOf(IllegalTransitionException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.ILLEGAL_TRANSITION);

            assertNoAuditNoEvent();
            assertThat(counter("grab_conflict_total")).isEqualTo(1);
            verify(grabLock).release(1L, "token");
        }

        @Test
        @DisplayName("Redis 前置锁被占:40904,连 SELECT 都不做(不占数据库连接),不释放别人的锁")
        void lockContendedRejectsBeforeDb() {
            loginAs(TestFixtures.agentA());
            when(grabLock.tryAcquire(1L)).thenReturn(Optional.empty());

            assertThatThrownBy(() -> service.grab(1L))
                    .isInstanceOf(BizException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.GRAB_CONTENDED);

            verify(ticketMapper, never()).selectById(anyLong());
            verify(txTemplate, never()).execute(any());
            verify(grabLock, never()).release(anyLong(), anyString());
            assertNothingPersisted();
        }

        @Test
        @DisplayName("Redis 不可用(fail-open,token 为空串):照常进库走条件更新,release 收到空 token 直接跳过")
        void lockUnavailableFallsOpen() {
            loginAs(TestFixtures.agentA());
            stored(1L, PENDING, 1L, null);
            when(grabLock.tryAcquire(1L)).thenReturn(Optional.of(""));
            when(ticketMapper.grabIfPending(anyLong(), anyLong(), any(), any())).thenReturn(1);

            TicketVO vo = service.grab(1L);

            assertThat(vo.status()).isEqualTo(ASSIGNED);
            verify(grabLock).release(1L, "");
        }

        @Test
        @DisplayName("已经 ASSIGNED 的单再抢 → 40901,异常里 from=ASSIGNED to=ASSIGNED;顺序场景不进 UPDATE")
        void grabAlreadyAssigned() {
            loginAs(TestFixtures.agentB());
            stored(1L, ASSIGNED, 1L, 3L);

            assertThatThrownBy(() -> service.grab(1L))
                    .isInstanceOf(IllegalTransitionException.class)
                    .satisfies(e -> {
                        assertThat(((IllegalTransitionException) e).getFrom()).isEqualTo(ASSIGNED);
                        assertThat(((IllegalTransitionException) e).getTo()).isEqualTo(ASSIGNED);
                    });
            assertNothingPersisted();
            verify(grabLock).release(1L, "token");
        }

        @Test
        @DisplayName("ESCALATED 的单不能抢(只能由组长指派)")
        void grabEscalated() {
            loginAs(TestFixtures.agentA());
            stored(1L, ESCALATED, 1L, null);
            assertThatThrownBy(() -> service.grab(1L)).isInstanceOf(IllegalTransitionException.class);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("跨组抢单 → 40301")
        void grabAcrossGroup() {
            loginAs(TestFixtures.agentC());
            stored(1L, PENDING, 1L, null);
            assertThatThrownBy(() -> service.grab(1L))
                    .isInstanceOf(AccessDeniedException.class)
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.FORBIDDEN);
            assertNothingPersisted();
        }
    }

    // ------------------------------------------------------------------ 指派 / 改派

    @Nested
    @DisplayName("assign:指派 / 改派")
    class Assign {

        @Test
        @DisplayName("PENDING → ASSIGNED 指派:状态流转 + STATUS_CHANGED + ASSIGNED")
        void assignPending() {
            loginAs(TestFixtures.leader1());
            stored(1L, PENDING, 1L, null);
            agentExists(4L, 1L);

            TicketVO vo = service.assign(1L, new AssignRequest(4L, "派给你"));

            assertThat(vo.status()).isEqualTo(ASSIGNED);
            assertThat(vo.assigneeId()).isEqualTo(4L);
            verify(auditLogService).record(eq(1L), eq(PENDING), eq(ASSIGNED), eq(2L), anyString(),
                    eq(AuditSource.MANUAL), org.mockito.ArgumentMatchers.contains("指派给 4"));
            assertThat(publishedEvents()).extracting(TicketDomainEvent::type)
                    .containsExactly(EventType.STATUS_CHANGED, EventType.ASSIGNED);
        }

        @Test
        @DisplayName("ASSIGNED → ASSIGNED 改派:只换人不换状态,审计 from=to=ASSIGNED,只发 ASSIGNED 事件")
        void reassign() {
            loginAs(TestFixtures.leader1());
            stored(1L, ASSIGNED, 1L, 3L);
            agentExists(4L, 1L);

            TicketVO vo = service.assign(1L, new AssignRequest(4L, null));

            assertThat(vo.status()).isEqualTo(ASSIGNED);
            assertThat(vo.assigneeId()).isEqualTo(4L);
            verify(auditLogService).record(eq(1L), eq(ASSIGNED), eq(ASSIGNED), eq(2L), anyString(),
                    eq(AuditSource.MANUAL), org.mockito.ArgumentMatchers.contains("改派 3 -> 4"));
            assertThat(publishedEvents()).extracting(TicketDomainEvent::type).containsExactly(EventType.ASSIGNED);
        }

        @Test
        @DisplayName("ESCALATED → ASSIGNED:升级单由组长重新指派,走状态机")
        void assignEscalated() {
            loginAs(TestFixtures.leader1());
            stored(1L, ESCALATED, 1L, 3L);
            agentExists(3L, 1L);

            TicketVO vo = service.assign(1L, new AssignRequest(3L, null));

            assertThat(vo.status()).isEqualTo(ASSIGNED);
            assertThat(publishedEvents()).extracting(TicketDomainEvent::type)
                    .containsExactly(EventType.STATUS_CHANGED, EventType.ASSIGNED);
        }

        @Test
        @DisplayName("PROCESSING 的单不能改派(PROCESSING -> ASSIGNED 不在迁移表里)→ 40901")
        void cannotAssignProcessing() {
            loginAs(TestFixtures.leader1());
            stored(1L, PROCESSING, 1L, 3L);
            agentExists(4L, 1L);
            assertThatThrownBy(() -> service.assign(1L, new AssignRequest(4L, null)))
                    .isInstanceOf(IllegalTransitionException.class);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("AGENT 改派 → 40302 垂直越权")
        void agentCannotAssign() {
            loginAs(TestFixtures.agentA());
            stored(1L, ASSIGNED, 1L, 3L);
            assertThatThrownBy(() -> service.assign(1L, new AssignRequest(4L, null)))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.ROLE_FORBIDDEN);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("别组组长改派 → 40301")
        void otherGroupLeaderCannotAssign() {
            loginAs(TestFixtures.leader2());
            stored(1L, ASSIGNED, 1L, 3L);
            assertThatThrownBy(() -> service.assign(1L, new AssignRequest(6L, null)))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.FORBIDDEN);
            assertNothingPersisted();
        }

        @Test
        @DisplayName("改派与抢单撞车:组长读到的快照已被抢单改过(updateById 影响 0 行)→ 40903,审计里不会出现假的 ASSIGNED→ASSIGNED")
        void reassignLosesRaceToGrab() {
            loginAs(TestFixtures.leader1());
            stored(1L, ASSIGNED, 1L, 3L);
            agentExists(4L, 1L);
            when(ticketMapper.updateById(any(Ticket.class))).thenReturn(0);

            assertThatThrownBy(() -> service.assign(1L, new AssignRequest(4L, null)))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.CONCURRENT_MODIFICATION);
            assertNoAuditNoEvent();
        }

        @Test
        @DisplayName("指派给不存在的坐席 → 40402")
        void assignToUnknownAgent() {
            loginAs(TestFixtures.admin());
            stored(1L, PENDING, 1L, null);
            when(agentService.getOrThrow(999L)).thenThrow(new NotFoundException(ErrorCode.AGENT_NOT_FOUND, 999L));
            assertThatThrownBy(() -> service.assign(1L, new AssignRequest(999L, null)))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.AGENT_NOT_FOUND);
        }
    }

    // ------------------------------------------------------------------ 查 / 改 / 删

    @Nested
    @DisplayName("get / update / delete / draftReply")
    class Others {

        @Test
        @DisplayName("get:agent_b 看 agent_a 的单 → 40301")
        void getForbidden() {
            loginAs(TestFixtures.agentB());
            stored(1L, ASSIGNED, 1L, 3L);
            assertThatThrownBy(() -> service.get(1L))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.FORBIDDEN);
        }

        @Test
        @DisplayName("update:已关闭的单不能改 → 40902")
        void updateClosed() {
            loginAs(TestFixtures.admin());
            stored(1L, CLOSED, 1L, 3L);
            assertThatThrownBy(() -> service.update(1L, new UpdateTicketRequest("新标题", "新内容")))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.TICKET_CLOSED);
            verify(ticketMapper, never()).updateById(any(Ticket.class));
        }

        @Test
        @DisplayName("update:正常修改标题内容")
        void updateOk() {
            loginAs(TestFixtures.agentA());
            Ticket t = stored(1L, PROCESSING, 1L, 3L);
            TicketVO vo = service.update(1L, new UpdateTicketRequest("新标题", "新内容"));
            assertThat(vo.title()).isEqualTo("新标题");
            verify(ticketMapper).updateById(t);
        }

        @Test
        @DisplayName("delete:LEADER → 40302;ADMIN → 逻辑删除")
        void deleteByRole() {
            loginAs(TestFixtures.leader1());
            assertThatThrownBy(() -> service.delete(1L))
                    .extracting(e -> ((BizException) e).getErrorCode()).isEqualTo(ErrorCode.ROLE_FORBIDDEN);
            verify(ticketMapper, never()).deleteById(anyLong());

            loginAs(TestFixtures.admin());
            stored(1L, CLOSED, 1L, 3L);
            service.delete(1L);
            verify(ticketMapper).deleteById(1L);
        }

        @Test
        @DisplayName("draftReply:把工单标题 / 内容 / 分类交给 LlmService,把结果原样装进 VO")
        void draftReplyDelegates() {
            loginAs(TestFixtures.agentA());
            Ticket t = stored(1L, PROCESSING, 1L, 3L);
            t.setCategory(TicketCategory.REFUND);
            when(llmService.draftReply(1L, t.getTitle(), t.getContent(), TicketCategory.REFUND))
                    .thenReturn(new DraftOutcome("模板草稿", true, DegradeReason.TIMEOUT, "mock-writer-v1", null, 3001, 9L));

            ReplyDraftVO vo = service.draftReply(1L);

            assertThat(vo.ticketId()).isEqualTo(1L);
            assertThat(vo.draft()).isEqualTo("模板草稿");
            assertThat(vo.degraded()).isTrue();
            assertThat(vo.degradeReason()).isEqualTo(DegradeReason.TIMEOUT);
            assertThat(vo.responseModel()).isNull();
            assertThat(vo.latencyMs()).isEqualTo(3001);
            verify(events, times(0)).publishEvent(any(Object.class));
        }
    }
}
