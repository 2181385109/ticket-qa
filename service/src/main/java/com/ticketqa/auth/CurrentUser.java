package com.ticketqa.auth;

import com.ticketqa.domain.enums.Role;

/**
 * 当前请求的操作者。从 X-User-Id 头解析、经坐席表校验后放进 UserContext。
 */
public record CurrentUser(Long id, String username, String displayName, Role role, Long groupId) {

    public boolean is(Role expected) {
        return role == expected;
    }
}
