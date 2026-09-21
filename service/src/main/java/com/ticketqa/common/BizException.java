package com.ticketqa.common;

/**
 * 业务异常基类。带错误码,由 {@link GlobalExceptionHandler} 翻译成 HTTP 响应。
 * 继承 RuntimeException(非受检异常):Spring 事务默认只对 RuntimeException 回滚,
 * 本项目所有 @Transactional 都显式写 rollbackFor = Exception.class,不依赖这个默认值。
 */
public class BizException extends RuntimeException {

    private final ErrorCode errorCode;

    public BizException(ErrorCode errorCode) {
        this(errorCode, errorCode.defaultMessage());
    }

    public BizException(ErrorCode errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }

    public ErrorCode getErrorCode() {
        return errorCode;
    }
}
