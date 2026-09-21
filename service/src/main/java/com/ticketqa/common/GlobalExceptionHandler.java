package com.ticketqa.common;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.stream.Collectors;

/**
 * 统一异常处理。@RestControllerAdvice = @ControllerAdvice + @ResponseBody,
 * 对所有 @RestController 抛出的异常做集中翻译,Controller 里不写 try-catch。
 * 匹配规则:按异常类型就近匹配(子类优先),所以 BizException 的处理器不会吞掉参数校验异常。
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BizException.class)
    public ResponseEntity<Result<Void>> handleBiz(BizException e) {
        ErrorCode code = e.getErrorCode();
        if (code.httpStatus().is5xxServerError()) {
            log.error("业务异常 code={} msg={}", code.code(), e.getMessage(), e);
        } else {
            log.warn("业务异常 code={} msg={}", code.code(), e.getMessage());
        }
        return ResponseEntity.status(code.httpStatus()).body(Result.fail(code, e.getMessage()));
    }

    /** @RequestBody 上的 @Valid 失败 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Result<Void>> handleBodyValidation(MethodArgumentNotValidException e) {
        String detail = e.getBindingResult().getFieldErrors().stream()
                .map(GlobalExceptionHandler::describe)
                .collect(Collectors.joining("; "));
        return badRequest(detail);
    }

    /** @RequestParam / @PathVariable 上的约束失败(需要类上有 @Validated) */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<Result<Void>> handleParamValidation(ConstraintViolationException e) {
        String detail = e.getConstraintViolations().stream()
                .map(ConstraintViolation::getMessage)
                .collect(Collectors.joining("; "));
        return badRequest(detail);
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, MethodArgumentTypeMismatchException.class,
            MissingServletRequestParameterException.class, MissingServletRequestPartException.class})
    public ResponseEntity<Result<Void>> handleUnreadable(Exception e) {
        return badRequest("请求格式错误: " + rootMessage(e));
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<Result<Void>> handleTooLarge(MaxUploadSizeExceededException e) {
        ErrorCode code = ErrorCode.ATTACHMENT_TOO_LARGE;
        return ResponseEntity.status(code.httpStatus()).body(Result.fail(code));
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Result<Void>> handleNoResource(NoResourceFoundException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(Result.fail(ErrorCode.TICKET_NOT_FOUND, "路径不存在: " + e.getResourcePath()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Result<Void>> handleUnknown(Exception e) {
        log.error("未处理异常", e);
        ErrorCode code = ErrorCode.INTERNAL_ERROR;
        return ResponseEntity.status(code.httpStatus()).body(Result.fail(code));
    }

    private static ResponseEntity<Result<Void>> badRequest(String detail) {
        ErrorCode code = ErrorCode.PARAM_INVALID;
        return ResponseEntity.status(code.httpStatus()).body(Result.fail(code, detail));
    }

    private static String describe(FieldError fe) {
        return fe.getField() + " " + fe.getDefaultMessage();
    }

    private static String rootMessage(Throwable t) {
        Throwable cur = t;
        while (cur.getCause() != null && cur.getCause() != cur) {
            cur = cur.getCause();
        }
        String msg = cur.getMessage();
        if (msg == null) {
            return cur.getClass().getSimpleName();
        }
        int nl = msg.indexOf('\n');
        return nl > 0 ? msg.substring(0, nl) : msg;
    }
}
