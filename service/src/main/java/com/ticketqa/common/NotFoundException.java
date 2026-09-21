package com.ticketqa.common;

public class NotFoundException extends BizException {

    public NotFoundException(ErrorCode errorCode, Object id) {
        super(errorCode, errorCode.defaultMessage() + ": " + id);
    }
}
