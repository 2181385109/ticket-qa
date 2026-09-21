package com.ticketqa.agent;

import com.ticketqa.auth.CurrentUser;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.common.NotFoundException;
import org.springframework.stereotype.Service;

import java.util.Optional;

@Service
public class AgentService {

    private final AgentCache agentCache;

    public AgentService(AgentCache agentCache) {
        this.agentCache = agentCache;
    }

    /** 鉴权拦截器用:停用的坐席视为不存在。 */
    public Optional<CurrentUser> findCurrentUser(Long id) {
        AgentSnapshot s = agentCache.findSnapshot(id);
        if (s == null || !s.isActive()) {
            return Optional.empty();
        }
        return Optional.of(new CurrentUser(s.getId(), s.getUsername(), s.getDisplayName(), s.getRole(), s.getGroupId()));
    }

    /** 改派 / 分配时校验目标坐席存在。 */
    public AgentSnapshot getOrThrow(Long id) {
        AgentSnapshot s = agentCache.findSnapshot(id);
        if (s == null) {
            throw new NotFoundException(ErrorCode.AGENT_NOT_FOUND, id);
        }
        return s;
    }
}
