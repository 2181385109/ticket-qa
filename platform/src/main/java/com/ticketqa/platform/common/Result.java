package com.ticketqa.platform.common;

/** 与被测服务同形状的统一返回体,平台自己的接口自动化(如果以后写)可以复用同一套断言 DSL。 */
public record Result<T>(int code, String message, T data) {

    public static <T> Result<T> ok(T data) {
        return new Result<>(0, "success", data);
    }

    public static <T> Result<T> fail(int code, String message) {
        return new Result<>(code, message, null);
    }
}
