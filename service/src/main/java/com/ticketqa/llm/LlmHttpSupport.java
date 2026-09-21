package com.ticketqa.llm;

import com.ticketqa.domain.enums.DegradeReason;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientResponseException;

import java.net.http.HttpTimeoutException;
import java.net.SocketTimeoutException;
import java.util.concurrent.TimeoutException;

/**
 * 两个 HTTP 实现共用的异常翻译:把 Spring RestClient 抛的异常映射成 DegradeReason。
 * 超时判定靠异常链里是否出现 HttpTimeoutException / TimeoutException / SocketTimeoutException——
 * JDK HttpClient 的 timeout 是"响应头到达"的整体超时,不是逐次 read 的超时。
 */
final class LlmHttpSupport {

    private LlmHttpSupport() {
    }

    static LlmException translate(RuntimeException e) {
        if (e instanceof ResourceAccessException) {
            if (isTimeout(e)) {
                return new LlmException(DegradeReason.TIMEOUT, "LLM 调用超时", e);
            }
            return new LlmException(DegradeReason.UPSTREAM_ERROR, "LLM 网络错误: " + rootMessage(e), e);
        }
        if (e instanceof RestClientResponseException re) {
            return new LlmException(DegradeReason.UPSTREAM_ERROR,
                    "LLM 返回 HTTP " + re.getStatusCode().value(), e);
        }
        if (e instanceof LlmException le) {
            return le;
        }
        return new LlmException(DegradeReason.BAD_RESPONSE, "LLM 响应无法解析: " + rootMessage(e), e);
    }

    private static boolean isTimeout(Throwable t) {
        Throwable cur = t;
        while (cur != null) {
            // JDK HttpClient 本身抛 HttpTimeoutException;Spring 的 JdkClientHttpRequest 用 readTimeout 等待时
            // 抛的是 java.util.concurrent.TimeoutException 包在 IOException 里——联调时靠这一条把 3s 超时从
            // UPSTREAM_ERROR 纠正成 TIMEOUT。SocketTimeoutException 是给 SimpleClientHttpRequestFactory 留的。
            if (cur instanceof HttpTimeoutException || cur instanceof SocketTimeoutException
                    || cur instanceof TimeoutException) {
                return true;
            }
            cur = cur.getCause() == cur ? null : cur.getCause();
        }
        return false;
    }

    private static String rootMessage(Throwable t) {
        Throwable cur = t;
        while (cur.getCause() != null && cur.getCause() != cur) {
            cur = cur.getCause();
        }
        return cur.getMessage() == null ? cur.getClass().getSimpleName() : cur.getMessage();
    }
}
