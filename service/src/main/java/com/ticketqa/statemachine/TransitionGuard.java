package com.ticketqa.statemachine;

import com.ticketqa.domain.entity.Ticket;

import java.time.LocalDateTime;
import java.util.Optional;

/**
 * 流转守卫:边在表里存在只说明"结构上允许",守卫再检查"此刻这张工单允不允许"。
 * 函数式接口(只有一个抽象方法),所以可以用 lambda 写:(ticket, now) -> ...
 *
 * 返回 Optional.empty() 表示放行;返回 Optional.of(原因) 表示拒绝,原因会进异常消息。
 */
@FunctionalInterface
public interface TransitionGuard {

    Optional<String> check(Ticket ticket, LocalDateTime now);
}
