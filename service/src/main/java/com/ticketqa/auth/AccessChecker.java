package com.ticketqa.auth;

import com.ticketqa.common.AccessDeniedException;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.domain.entity.Ticket;
import com.ticketqa.domain.enums.Role;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.Objects;

/**
 * 授权规则的唯一出口,被 Service 层调用(不是 Controller)。
 *
 *   AGENT  只能读写分配给自己的工单;可在本组抢 PENDING 单
 *   LEADER 本组全部工单可读可写,可改派
 *   ADMIN  全权
 *
 * 水平越权 → FORBIDDEN(40301):角色够,但不是你的单
 * 垂直越权 → ROLE_FORBIDDEN(40302):角色不够
 */
@Component
public class AccessChecker {

    public void checkRead(CurrentUser user, Ticket ticket) {
        if (!canAccess(user, ticket)) {
            throw new AccessDeniedException(ErrorCode.FORBIDDEN, "无权查看工单 " + ticket.getId());
        }
    }

    public void checkWrite(CurrentUser user, Ticket ticket) {
        if (!canAccess(user, ticket)) {
            throw new AccessDeniedException(ErrorCode.FORBIDDEN, "无权操作工单 " + ticket.getId());
        }
    }

    /** 抢单:同组即可,不要求已分配给自己(PENDING 单本来就没有 assignee) */
    public void checkGrab(CurrentUser user, Ticket ticket) {
        if (user.is(Role.ADMIN)) {
            return;
        }
        if (!Objects.equals(ticket.getGroupId(), user.groupId())) {
            throw new AccessDeniedException(ErrorCode.FORBIDDEN, "只能抢本组的工单");
        }
    }

    /** 改派:LEADER 限本组,ADMIN 全权,AGENT 不行(垂直越权点) */
    public void checkAssign(CurrentUser user, Ticket ticket) {
        requireRole(user, Role.LEADER, Role.ADMIN);
        if (user.is(Role.LEADER) && !Objects.equals(ticket.getGroupId(), user.groupId())) {
            throw new AccessDeniedException(ErrorCode.FORBIDDEN, "只能改派本组的工单");
        }
    }

    public void requireRole(CurrentUser user, Role... allowed) {
        if (Arrays.stream(allowed).noneMatch(user::is)) {
            throw new AccessDeniedException(ErrorCode.ROLE_FORBIDDEN,
                    "需要角色 " + Arrays.toString(allowed) + ",当前为 " + user.role());
        }
    }

    private static boolean canAccess(CurrentUser user, Ticket ticket) {
        // switch 表达式(Java 14+):对枚举穷举,漏了分支编译不过
        return switch (user.role()) {
            case ADMIN -> true;
            case LEADER -> Objects.equals(ticket.getGroupId(), user.groupId());
            case AGENT -> ticket.getAssigneeId() != null && Objects.equals(ticket.getAssigneeId(), user.id());
        };
    }
}
