package com.ticketqa.ticket;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.ticketqa.agent.AgentService;
import com.ticketqa.agent.AgentSnapshot;
import com.ticketqa.audit.AuditLogService;
import com.ticketqa.auth.AccessChecker;
import com.ticketqa.auth.CurrentUser;
import com.ticketqa.auth.UserContext;
import com.ticketqa.common.BizException;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.common.IllegalTransitionException;
import com.ticketqa.common.NotFoundException;
import com.ticketqa.common.TraceIdFilter;
import com.ticketqa.config.AppProperties;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.AuditSource;
import com.ticketqa.domain.enums.EventType;
import com.ticketqa.domain.enums.Role;
import com.ticketqa.domain.enums.TicketStatus;
import com.ticketqa.llm.ClassifyOutcome;
import com.ticketqa.llm.DraftOutcome;
import com.ticketqa.llm.LlmCallLogService;
import com.ticketqa.llm.LlmService;
import com.ticketqa.mapper.TicketMapper;
import com.ticketqa.statemachine.TicketStateMachine;
import com.ticketqa.ticket.dto.AssignRequest;
import com.ticketqa.ticket.dto.AuditLogVO;
import com.ticketqa.ticket.dto.CreateTicketRequest;
import com.ticketqa.ticket.dto.PageVO;
import com.ticketqa.ticket.dto.ReplyDraftVO;
import com.ticketqa.ticket.dto.TicketVO;
import com.ticketqa.ticket.dto.TransitionRequest;
import com.ticketqa.ticket.dto.UpdateTicketRequest;
import com.ticketqa.ticket.event.TicketDomainEvent;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Clock;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/**
 * 工单核心服务。所有权限校验、状态机、审计、事件都从这里出去——Controller 只做参数绑定。
 *
 * 事务边界(ADR-002):
 *   - 状态变更 + 审计日志 在同一个事务里,要么都落库要么都不落
 *   - MQ 发送在事务提交后(TicketEventPublisher 监听 AFTER_COMMIT)
 *   - 创建工单时 LLM 调用放在事务之外:3 秒的 HTTP 等待不能占着数据库连接
 *   - 抢单的 Redis 前置锁在事务之外:被锁挡掉的请求不该占用数据库连接
 *
 * 并发写的约束(ADR-016 / ADR-017):
 *   - 每条 UPDATE 都带 version(乐观锁),受影响 0 行 → 40903,不写审计不发事件
 *   - 抢单额外把 status = 'PENDING' 写进 WHERE(条件更新),受影响 0 行 → 40901
 *   - 审计的 from_status 只在 UPDATE 受影响 1 行之后写,所以它一定等于写之前那一行的真实状态
 */
@Service
public class TicketService {

    private static final Logger log = LoggerFactory.getLogger(TicketService.class);

    private final TicketMapper ticketMapper;
    private final TicketStateMachine stateMachine;
    private final AccessChecker access;
    private final AuditLogService auditLogService;
    private final AgentService agentService;
    private final LlmService llmService;
    private final LlmCallLogService llmCallLogService;
    private final ApplicationEventPublisher events;
    private final TransactionTemplate txTemplate;
    private final AppProperties props;
    private final Clock clock;
    private final GrabLock grabLock;
    private final TicketNoGenerator ticketNoGenerator;
    private final Counter grabConflictCounter;
    private final Counter versionConflictCounter;

    public TicketService(TicketMapper ticketMapper, TicketStateMachine stateMachine, AccessChecker access,
                         AuditLogService auditLogService, AgentService agentService, LlmService llmService,
                         LlmCallLogService llmCallLogService, ApplicationEventPublisher events,
                         TransactionTemplate txTemplate, AppProperties props, Clock clock,
                         GrabLock grabLock, TicketNoGenerator ticketNoGenerator, MeterRegistry registry) {
        this.ticketMapper = ticketMapper;
        this.stateMachine = stateMachine;
        this.access = access;
        this.auditLogService = auditLogService;
        this.agentService = agentService;
        this.llmService = llmService;
        this.llmCallLogService = llmCallLogService;
        this.events = events;
        this.txTemplate = txTemplate;
        this.props = props;
        this.clock = clock;
        this.grabLock = grabLock;
        this.ticketNoGenerator = ticketNoGenerator;
        this.grabConflictCounter = Counter.builder("grab_conflict_total")
                .description("抢单条件更新影响 0 行(进库后发现已被抢)的次数").register(registry);
        this.versionConflictCounter = Counter.builder("ticket_version_conflict_total")
                .description("乐观锁冲突(updateById 影响 0 行)的次数").register(registry);
    }

    // ------------------------------------------------------------------ 创建

    /**
     * 创建工单:LLM 分类(事务外)→ 落库 + 审计 + 事件(事务内)。
     * 这里用 TransactionTemplate 而不是 @Transactional:方法的前半段(LLM 调用)不能在事务里,
     * 而同一个类里调用自己的 @Transactional 方法不经过代理、注解不生效,所以改用编程式事务把边界画清楚。
     */
    public TicketVO create(CreateTicketRequest req) {
        CurrentUser user = UserContext.require();
        LocalDateTime now = LocalDateTime.now(clock);

        ClassifyOutcome outcome = llmService.classify(req.title(), req.content());

        Ticket created = txTemplate.execute(status -> {
            Ticket t = new Ticket();
            t.setTicketNo(ticketNoGenerator.generate(now));
            t.setTitle(req.title());
            t.setContent(req.content());
            t.setCategory(outcome.category());
            t.setPriority(outcome.priority());
            t.setStatus(TicketStatus.PENDING);
            t.setCustomerId(req.customerId());
            t.setGroupId(req.groupIdOrDefault());
            t.setCreatedBy(user.id());
            // SLA 计时起点 = 创建时刻(取 LLM 调用之前的 now,保证 sla_deadline == created_at + 时限)
            t.setCreatedAt(now);
            t.setUpdatedAt(now);
            t.setSlaDeadline(now.plusMinutes(props.sla().responseMinutes().get(outcome.priority())));
            ticketMapper.insert(t);

            llmCallLogService.bindTicket(outcome.callLogId(), t.getId());
            auditLogService.record(t.getId(), null, TicketStatus.PENDING, user.id(), user.displayName(),
                    AuditSource.LLM, outcome.describe());
            publish(EventType.STATUS_CHANGED, t, null, TicketStatus.PENDING, user, AuditSource.LLM, now);
            return t;
        });
        log.info("工单创建 id={} no={} category={} priority={} degraded={}",
                created.getId(), created.getTicketNo(), outcome.category(), outcome.priority(), outcome.degraded());
        return TicketConverter.toVO(created);
    }

    // ------------------------------------------------------------------ 查询

    public TicketVO get(Long id) {
        CurrentUser user = UserContext.require();
        Ticket ticket = getOrThrow(id);
        access.checkRead(user, ticket);
        return TicketConverter.toVO(ticket);
    }

    /** 列表按角色自动收窄范围:AGENT 只看自己的,LEADER 看本组,ADMIN 看全部。 */
    public PageVO<TicketVO> list(TicketStatus status, long page, long size) {
        CurrentUser user = UserContext.require();
        LambdaQueryWrapper<Ticket> query = new LambdaQueryWrapper<Ticket>()
                .eq(status != null, Ticket::getStatus, status)
                .eq(user.is(Role.AGENT), Ticket::getAssigneeId, user.id())
                .eq(user.is(Role.LEADER), Ticket::getGroupId, user.groupId())
                .orderByDesc(Ticket::getId);
        Page<Ticket> result = ticketMapper.selectPage(new Page<>(page, size), query);
        List<TicketVO> records = result.getRecords().stream().map(TicketConverter::toVO).toList();
        return new PageVO<>(records, result.getTotal(), result.getCurrent(), result.getSize());
    }

    public List<AuditLogVO> auditLogs(Long id) {
        CurrentUser user = UserContext.require();
        Ticket ticket = getOrThrow(id);
        access.checkRead(user, ticket);
        return auditLogService.listByTicket(id).stream().map(TicketConverter::toVO).toList();
    }

    // ------------------------------------------------------------------ 修改 / 删除

    @Transactional(rollbackFor = Exception.class)
    public TicketVO update(Long id, UpdateTicketRequest req) {
        CurrentUser user = UserContext.require();
        Ticket ticket = getOrThrow(id);
        access.checkWrite(user, ticket);
        if (ticket.getStatus() == TicketStatus.CLOSED) {
            throw new BizException(ErrorCode.TICKET_CLOSED);
        }
        ticket.setTitle(req.title());
        ticket.setContent(req.content());
        updateOrConflict(ticket);
        return TicketConverter.toVO(ticket);
    }

    @Transactional(rollbackFor = Exception.class)
    public void delete(Long id) {
        CurrentUser user = UserContext.require();
        access.requireRole(user, Role.ADMIN);
        getOrThrow(id);
        ticketMapper.deleteById(id);
    }

    // ------------------------------------------------------------------ 状态流转

    @Transactional(rollbackFor = Exception.class)
    public TicketVO transit(Long id, TransitionRequest req) {
        CurrentUser user = UserContext.require();
        Ticket ticket = getOrThrow(id);
        access.checkWrite(user, ticket);
        LocalDateTime now = LocalDateTime.now(clock);

        if (req.target() == TicketStatus.ASSIGNED) {
            access.checkAssign(user, ticket);
            ticket.setAssigneeId(requireAssignee(req.assigneeId(), ticket));
        }
        TicketStatus from = stateMachine.transit(ticket, req.target(), now);
        updateOrConflict(ticket);   // 影响 1 行 ⇒ 库里写之前的状态就是 from(ADR-017)

        auditLogService.record(id, from, req.target(), user.id(), user.displayName(), AuditSource.MANUAL, req.remark());
        publish(EventType.STATUS_CHANGED, ticket, from, req.target(), user, AuditSource.MANUAL, now);
        if (req.target() == TicketStatus.ASSIGNED) {
            publish(EventType.ASSIGNED, ticket, from, req.target(), user, AuditSource.MANUAL, now);
        }
        return TicketConverter.toVO(ticket);
    }

    /**
     * 坐席抢单:PENDING 的工单分配给自己。三层(ADR-016):
     *   1. Redis 前置锁(事务外,削峰):同一张单同一时刻只放一个请求进库,其余直接 40904;Redis 不可用则放行
     *   2. 条件 UPDATE(根治):status = 'PENDING' AND version = ? 写在 WHERE 里,受影响 0 行 → 40901
     *   3. version(通用兜底):所有写路径共用,抢单这里与第 2 层合并在同一条语句里
     * 不用 @Transactional 而用 TransactionTemplate:锁要在事务开始前拿、提交后放,注解式事务包不住这个顺序
     * (同类自调用又不走代理,和 create() 是同一个理由)。
     */
    public TicketVO grab(Long id) {
        CurrentUser user = UserContext.require();
        Optional<String> lock = grabLock.tryAcquire(id);
        if (lock.isEmpty()) {
            throw new BizException(ErrorCode.GRAB_CONTENDED, "工单 " + id + " 正在被其他坐席抢,请稍后重试");
        }
        try {
            return txTemplate.execute(status -> grabInTransaction(id, user));
        } finally {
            grabLock.release(id, lock.get());
        }
    }

    private TicketVO grabInTransaction(Long id, CurrentUser user) {
        Ticket ticket = getOrThrow(id);
        access.checkGrab(user, ticket);
        if (ticket.getStatus() != TicketStatus.PENDING) {
            // 顺序场景(已被抢后再抢)在这里就能拒绝,不必进 UPDATE;并发场景靠下面的条件更新
            throw new IllegalTransitionException(ticket.getStatus(), TicketStatus.ASSIGNED, "只能抢 PENDING 状态的工单,当前为 " + ticket.getStatus());
        }
        LocalDateTime now = LocalDateTime.now(clock);
        stateMachine.assertAllowed(ticket, TicketStatus.ASSIGNED, now);

        int affected = ticketMapper.grabIfPending(id, user.id(), ticket.getVersion(), now);
        if (affected == 0) {
            grabConflictCounter.increment();
            log.info("抢单冲突:条件更新影响 0 行 ticketId={} userId={}", id, user.id());
            throw new IllegalTransitionException(TicketStatus.PENDING, TicketStatus.ASSIGNED,
                    "工单 " + id + " 已被其他坐席抢走或状态已变化");
        }
        // 走到这里,库里那一行在被改之前确实是 PENDING——from 不是内存快照,是 WHERE 断言过的事实
        TicketStatus from = TicketStatus.PENDING;
        ticket.setStatus(TicketStatus.ASSIGNED);
        ticket.setAssigneeId(user.id());
        ticket.setUpdatedAt(now);
        ticket.setVersion(ticket.getVersion() == null ? null : ticket.getVersion() + 1);

        auditLogService.record(id, from, TicketStatus.ASSIGNED, user.id(), user.displayName(), AuditSource.MANUAL, "抢单");
        publish(EventType.STATUS_CHANGED, ticket, from, TicketStatus.ASSIGNED, user, AuditSource.MANUAL, now);
        publish(EventType.ASSIGNED, ticket, from, TicketStatus.ASSIGNED, user, AuditSource.MANUAL, now);
        return TicketConverter.toVO(ticket);
    }

    /**
     * 指派 / 改派(LEADER 本组、ADMIN 全权):
     *   PENDING / ESCALATED → ASSIGNED 是状态流转;
     *   ASSIGNED → ASSIGNED 只换人不换状态,审计里 from=to=ASSIGNED,备注写明改派。
     */
    @Transactional(rollbackFor = Exception.class)
    public TicketVO assign(Long id, AssignRequest req) {
        CurrentUser user = UserContext.require();
        Ticket ticket = getOrThrow(id);
        access.checkAssign(user, ticket);
        LocalDateTime now = LocalDateTime.now(clock);
        Long previous = ticket.getAssigneeId();
        Long assignee = requireAssignee(req.assigneeId(), ticket);

        TicketStatus from;
        String remark;
        if (ticket.getStatus() == TicketStatus.ASSIGNED) {
            from = TicketStatus.ASSIGNED;
            ticket.setAssigneeId(assignee);
            remark = "改派 " + previous + " -> " + assignee + (req.remark() == null ? "" : ";" + req.remark());
        } else {
            ticket.setAssigneeId(assignee);
            from = stateMachine.transit(ticket, TicketStatus.ASSIGNED, now);
            remark = "指派给 " + assignee + (req.remark() == null ? "" : ";" + req.remark());
        }
        updateOrConflict(ticket);   // 改派与抢单撞车时,晚到的一方在这里拿到 0 行 → 40903

        auditLogService.record(id, from, TicketStatus.ASSIGNED, user.id(), user.displayName(), AuditSource.MANUAL, remark);
        if (from != TicketStatus.ASSIGNED) {
            publish(EventType.STATUS_CHANGED, ticket, from, TicketStatus.ASSIGNED, user, AuditSource.MANUAL, now);
        }
        publish(EventType.ASSIGNED, ticket, from, TicketStatus.ASSIGNED, user, AuditSource.MANUAL, now);
        return TicketConverter.toVO(ticket);
    }

    // ------------------------------------------------------------------ LLM 回复草稿

    /** 不加 @Transactional:LLM 调用不该占着数据库连接;调用记录由 LlmCallLogService 用独立事务落盘。 */
    public ReplyDraftVO draftReply(Long id) {
        CurrentUser user = UserContext.require();
        Ticket ticket = getOrThrow(id);
        access.checkWrite(user, ticket);
        DraftOutcome outcome = llmService.draftReply(id, ticket.getTitle(), ticket.getContent(), ticket.getCategory());
        return new ReplyDraftVO(id, outcome.draft(), outcome.degraded(), outcome.degradeReason(),
                outcome.requestModel(), outcome.responseModel(), outcome.latencyMs());
    }

    // ------------------------------------------------------------------ 内部

    /** 给 AttachmentService 复用,所以是 public;不做权限校验,调用方自己校验 */
    public Ticket getOrThrow(Long id) {
        Ticket ticket = ticketMapper.selectById(id);
        if (ticket == null) {
            throw new NotFoundException(ErrorCode.TICKET_NOT_FOUND, id);
        }
        return ticket;
    }

    private Long requireAssignee(Long assigneeId, Ticket ticket) {
        if (assigneeId == null) {
            throw new BizException(ErrorCode.ASSIGNEE_REQUIRED);
        }
        AgentSnapshot agent = agentService.getOrThrow(assigneeId);
        if (!Objects.equals(agent.getGroupId(), ticket.getGroupId())) {
            throw new BizException(ErrorCode.ASSIGNEE_GROUP_MISMATCH,
                    "坐席 " + assigneeId + " 属于组 " + agent.getGroupId() + ",工单属于组 " + ticket.getGroupId());
        }
        return assigneeId;
    }

    private void publish(EventType type, Ticket t, TicketStatus from, TicketStatus to,
                         CurrentUser operator, AuditSource source, LocalDateTime now) {
        events.publishEvent(new TicketDomainEvent(type, t.getId(), t.getTicketNo(), from, to, t.getAssigneeId(),
                operator == null ? null : operator.id(), operator == null ? "SCHEDULER" : operator.displayName(),
                source, TraceIdFilter.current(), now));
    }

    /**
     * 带乐观锁的更新:updateById 被 OptimisticLockerInnerInterceptor 改写成 "... WHERE id=? AND version=?",
     * 受影响 0 行说明这份快照在 SELECT 之后被别的事务改过——此时既不能落审计(from 不可信),也不能发事件。
     * 抛异常让事务回滚,客户端收到 40903 后重新读取再操作。
     */
    private void updateOrConflict(Ticket ticket) {
        int affected = ticketMapper.updateById(ticket);
        if (affected == 0) {
            versionConflictCounter.increment();
            log.info("乐观锁冲突 ticketId={} version={}", ticket.getId(), ticket.getVersion());
            throw new BizException(ErrorCode.CONCURRENT_MODIFICATION,
                    "工单 " + ticket.getId() + " 已被其他操作修改(version=" + ticket.getVersion() + "),请刷新后重试");
        }
    }
}
