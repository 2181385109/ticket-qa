package com.ticketqa.common;

import org.slf4j.MDC;

/**
 * 统一响应体。所有接口都返回它,不裸返实体。
 * record:不可变数据类,自动生成构造器 / 访问器 / equals / hashCode / toString。
 *
 * @param <T> data 的类型,由各接口自行决定
 */
public record Result<T>(int code, String message, T data, String traceId) {

    public static <T> Result<T> ok(T data) {
        return new Result<>(ErrorCode.OK.code(), ErrorCode.OK.defaultMessage(), data, currentTraceId());
    }

    public static Result<Void> ok() {
        return ok(null);
    }

    public static <T> Result<T> fail(ErrorCode errorCode, String message) {
        return new Result<>(errorCode.code(), message, null, currentTraceId());
    }

    public static <T> Result<T> fail(ErrorCode errorCode) {
        return fail(errorCode, errorCode.defaultMessage());
    }

    private static String currentTraceId() {
        return MDC.get(TraceIdFilter.MDC_KEY);
    }
}
