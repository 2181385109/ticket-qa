package com.ticketqa.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ticketqa.domain.entity.Ticket;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 工单 Mapper。BaseMapper<Ticket> 提供 insert / selectById / updateById / selectPage 等通用方法,
 * 这里只补三条手写 SQL:SLA 扫描的范围查询、SLA 升级的条件更新、抢单的条件更新。
 *
 * 两条条件更新的共同点(ADR-016 / ADR-017):把"当前状态是不是 X"这个判断放进 UPDATE 的 WHERE 里,
 * 让 MySQL 在持有行锁的那一刻去判断,而不是应用层先 SELECT 再判断——SELECT 看到的是事务快照,
 * UPDATE 看到的是最新已提交版本,两者之间别的事务随时可能提交。受影响行数为 1 就等于
 * "写之前那一行的 status 确实等于 WHERE 里断言的值",审计的 from_status 直接用这个值,不会记出没发生过的转换。
 */
public interface TicketMapper extends BaseMapper<Ticket> {

    /**
     * 找出已到响应截止时限、仍未进入 PROCESSING、且从未被升级过的工单。
     * 闭区间:sla_deadline <= now,恰好等于即算超时(ADR-006)。
     */
    @Select("""
            SELECT id FROM ticket
             WHERE status IN ('PENDING', 'ASSIGNED')
               AND escalated_at IS NULL
               AND sla_deadline <= #{now}
               AND deleted = 0
             ORDER BY sla_deadline
             LIMIT #{limit}
            """)
    List<Long> selectSlaOverdueIds(@Param("now") LocalDateTime now, @Param("limit") int limit);

    /**
     * SLA 升级的条件更新:只有仍处于 {@code from} 状态、版本未变、且未升级过的行才会被改。
     * 返回受影响行数,0 表示别的线程 / 实例已经处理过,或工单在扫描与升级之间被人流转了——
     * 后者由下一轮扫描重新判断(escalated_at 仍为空)。这就是"同一工单不能被升级两次"的实现(ADR-006),
     * 也是审计 from_status 必须等于写时刻前值的实现(ADR-017):status = #{from} 写在 WHERE 里。
     */
    @Update("""
            UPDATE ticket
               SET status = 'ESCALATED', escalated_at = #{now}, updated_at = #{now}, version = version + 1
             WHERE id = #{id}
               AND status = #{from}
               AND status IN ('PENDING', 'ASSIGNED')
               AND version = #{version}
               AND escalated_at IS NULL
               AND deleted = 0
            """)
    int escalateIfStillUnresponded(@Param("id") Long id, @Param("from") String from,
                                   @Param("version") Integer version, @Param("now") LocalDateTime now);

    /**
     * 抢单的条件更新(ADR-016 的根治手段):status = 'PENDING' 和 version 都写在 WHERE 里。
     * N 个事务同时执行这条语句,InnoDB 在行锁上把它们排成队,第一个把 status 改成 ASSIGNED 并提交后,
     * 后面的每一个在拿到锁重新求值 WHERE 时都得到 0 行——不需要应用层做任何判断,也不依赖 Redis。
     */
    @Update("""
            UPDATE ticket
               SET status = 'ASSIGNED', assignee_id = #{assigneeId}, updated_at = #{now}, version = version + 1
             WHERE id = #{id}
               AND status = 'PENDING'
               AND version = #{version}
               AND deleted = 0
            """)
    int grabIfPending(@Param("id") Long id, @Param("assigneeId") Long assigneeId,
                      @Param("version") Integer version, @Param("now") LocalDateTime now);
}
