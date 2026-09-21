package com.ticketqa.agent;

import com.ticketqa.domain.enums.Role;

/**
 * 放进 Redis 缓存的坐席快照。用普通类而不是 record:Jackson 带类型信息的多态反序列化
 * 对"有无参构造 + setter"的类最稳,这里不想为了缓存去调 Jackson 的 record 兼容细节。
 */
public class AgentSnapshot {

    private Long id;
    private String username;
    private String displayName;
    private Role role;
    private Long groupId;
    private boolean active;

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getDisplayName() {
        return displayName;
    }

    public void setDisplayName(String displayName) {
        this.displayName = displayName;
    }

    public Role getRole() {
        return role;
    }

    public void setRole(Role role) {
        this.role = role;
    }

    public Long getGroupId() {
        return groupId;
    }

    public void setGroupId(Long groupId) {
        this.groupId = groupId;
    }

    public boolean isActive() {
        return active;
    }

    public void setActive(boolean active) {
        this.active = active;
    }
}
