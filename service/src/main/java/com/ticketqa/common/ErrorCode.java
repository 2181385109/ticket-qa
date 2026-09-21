package com.ticketqa.common;

import org.springframework.http.HttpStatus;

/**
 * 业务错误码。前两位对应 HTTP 状态,后三位是业务序号,例如 40901 → HTTP 409。
 * 接口自动化用 code 断言,不依赖 message 文案。
 */
public enum ErrorCode {

    OK(0, HttpStatus.OK, "success"),

    PARAM_INVALID(40001, HttpStatus.BAD_REQUEST, "参数校验失败"),
    ASSIGNEE_REQUIRED(40002, HttpStatus.BAD_REQUEST, "流转到 ASSIGNED 必须指定坐席"),
    ASSIGNEE_GROUP_MISMATCH(40003, HttpStatus.BAD_REQUEST, "坐席与工单不属于同一客服组"),

    UNAUTHENTICATED(40101, HttpStatus.UNAUTHORIZED, "缺少或无效的 X-User-Id"),

    FORBIDDEN(40301, HttpStatus.FORBIDDEN, "无权操作该工单"),
    ROLE_FORBIDDEN(40302, HttpStatus.FORBIDDEN, "当前角色无权执行该操作"),

    TICKET_NOT_FOUND(40401, HttpStatus.NOT_FOUND, "工单不存在"),
    AGENT_NOT_FOUND(40402, HttpStatus.NOT_FOUND, "坐席不存在"),
    ATTACHMENT_NOT_FOUND(40403, HttpStatus.NOT_FOUND, "附件不存在"),

    ILLEGAL_TRANSITION(40901, HttpStatus.CONFLICT, "非法的状态流转"),
    TICKET_CLOSED(40902, HttpStatus.CONFLICT, "工单已关闭,不能修改"),
    CONCURRENT_MODIFICATION(40903, HttpStatus.CONFLICT, "工单已被其他操作修改,请刷新后重试"),
    GRAB_CONTENDED(40904, HttpStatus.CONFLICT, "工单正在被其他坐席抢,请稍后重试"),

    ATTACHMENT_TOO_LARGE(41301, HttpStatus.PAYLOAD_TOO_LARGE, "附件超过 5MB"),
    ATTACHMENT_EMPTY(41501, HttpStatus.UNSUPPORTED_MEDIA_TYPE, "附件为空"),
    ATTACHMENT_EXT_NOT_ALLOWED(41502, HttpStatus.UNSUPPORTED_MEDIA_TYPE, "扩展名不在白名单"),
    ATTACHMENT_MIME_MISMATCH(41503, HttpStatus.UNSUPPORTED_MEDIA_TYPE, "文件内容与扩展名不符"),

    INTERNAL_ERROR(50000, HttpStatus.INTERNAL_SERVER_ERROR, "服务内部错误"),
    UPSTREAM_ERROR(50201, HttpStatus.BAD_GATEWAY, "下游服务异常");

    private final int code;
    private final HttpStatus httpStatus;
    private final String defaultMessage;

    ErrorCode(int code, HttpStatus httpStatus, String defaultMessage) {
        this.code = code;
        this.httpStatus = httpStatus;
        this.defaultMessage = defaultMessage;
    }

    public int code() {
        return code;
    }

    public HttpStatus httpStatus() {
        return httpStatus;
    }

    public String defaultMessage() {
        return defaultMessage;
    }
}
