package com.ticketqa.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketqa.agent.AgentService;
import com.ticketqa.common.ErrorCode;
import com.ticketqa.common.Result;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.io.IOException;
import java.util.Optional;

/**
 * 认证(你是谁)。简化为 X-User-Id 头 → 查坐席表(走 Redis 缓存)→ 放进 UserContext。
 * 授权(你能不能)不在这里做,在 Service 层的 AccessChecker(CLAUDE.md §5.6,ADR-007)。
 * 没有密码、没有 token:这是测试系统,不是生产系统,鉴权强度不是本项目的被测点。
 */
@Component
public class AuthInterceptor implements HandlerInterceptor {

    public static final String HEADER = "X-User-Id";

    private final AgentService agentService;
    private final ObjectMapper objectMapper;

    public AuthInterceptor(AgentService agentService, ObjectMapper objectMapper) {
        this.agentService = agentService;
        this.objectMapper = objectMapper;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws IOException {
        String raw = request.getHeader(HEADER);
        Optional<CurrentUser> user = parseId(raw).flatMap(agentService::findCurrentUser);
        if (user.isEmpty()) {
            reject(response);
            return false;
        }
        UserContext.set(user.get());
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        UserContext.clear();
    }

    private static Optional<Long> parseId(String raw) {
        if (raw == null || raw.isBlank()) {
            return Optional.empty();
        }
        try {
            return Optional.of(Long.parseLong(raw.trim()));
        } catch (NumberFormatException e) {
            return Optional.empty();
        }
    }

    private void reject(HttpServletResponse response) throws IOException {
        ErrorCode code = ErrorCode.UNAUTHENTICATED;
        response.setStatus(code.httpStatus().value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write(objectMapper.writeValueAsString(Result.fail(code)));
    }
}
