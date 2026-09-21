package com.ticketqa.auth;

import com.ticketqa.common.AccessDeniedException;
import com.ticketqa.common.ErrorCode;

import java.util.Optional;

/**
 * 把当前用户挂在线程上(ThreadLocal),Service 层不用从 Controller 一层层传参数。
 * Tomcat 用线程池处理请求,线程会被复用,所以拦截器 afterCompletion 里必须 clear(),
 * 否则上一个请求的用户会"漏"给下一个请求——这是 ThreadLocal 最经典的坑。
 */
public final class UserContext {

    private static final ThreadLocal<CurrentUser> HOLDER = new ThreadLocal<>();

    private UserContext() {
    }

    public static void set(CurrentUser user) {
        HOLDER.set(user);
    }

    public static Optional<CurrentUser> get() {
        return Optional.ofNullable(HOLDER.get());
    }

    /** Service 层用这个:没登录直接 401,而不是 NPE。 */
    public static CurrentUser require() {
        return get().orElseThrow(() -> new AccessDeniedException(ErrorCode.UNAUTHENTICATED, "未登录"));
    }

    public static void clear() {
        HOLDER.remove();
    }
}
