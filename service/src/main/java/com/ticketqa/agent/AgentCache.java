package com.ticketqa.agent;

import com.ticketqa.config.CacheConfig;
import com.ticketqa.domain.entity.Agent;
import com.ticketqa.mapper.AgentMapper;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Component;

/**
 * 坐席快照缓存(Redis)。
 *
 * 为什么单独一个 Bean 而不是直接写在 AgentService 里:
 * @Cacheable 靠 Spring 代理生效——调用方拿到的是代理对象,代理先查缓存,未命中才调真方法。
 * 如果 AgentService 内部一个方法调用同类的另一个 @Cacheable 方法,走的是 this,不经过代理,缓存失效。
 * 拆成独立 Bean 后,AgentService 注入的是 AgentCache 的代理,每次调用都会经过缓存逻辑。
 * (@Transactional 的失效场景与此同理,见 walkthrough 第 6 节。)
 */
@Component
public class AgentCache {

    private final AgentMapper agentMapper;

    public AgentCache(AgentMapper agentMapper) {
        this.agentMapper = agentMapper;
    }

    /** unless = "#result == null":查不到不缓存,否则新建坐席后 10 分钟内都会被当成不存在。 */
    @Cacheable(cacheNames = CacheConfig.CACHE_AGENTS, key = "#id", unless = "#result == null")
    public AgentSnapshot findSnapshot(Long id) {
        Agent agent = agentMapper.selectById(id);
        if (agent == null) {
            return null;
        }
        AgentSnapshot s = new AgentSnapshot();
        s.setId(agent.getId());
        s.setUsername(agent.getUsername());
        s.setDisplayName(agent.getDisplayName());
        s.setRole(agent.getRole());
        s.setGroupId(agent.getGroupId());
        s.setActive(Boolean.TRUE.equals(agent.getActive()));
        return s;
    }
}
