package com.ticketqa.common;

/**
 * 越权。水平越权(访问别人的工单)和垂直越权(角色不够)都走这里,
 * 用不同错误码区分,方便安全用例断言。
 */
public class AccessDeniedException extends BizException {

    public AccessDeniedException(ErrorCode errorCode, String message) {
        super(errorCode, message);
    }
}
