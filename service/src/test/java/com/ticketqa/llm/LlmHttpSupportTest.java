package com.ticketqa.llm;

import com.ticketqa.domain.enums.DegradeReason;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.HttpServerErrorException;
import org.springframework.web.client.ResourceAccessException;

import java.io.IOException;
import java.net.SocketTimeoutException;
import java.net.http.HttpConnectTimeoutException;
import java.net.http.HttpTimeoutException;
import java.util.concurrent.TimeoutException;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 异常 → 降级原因 的翻译表(等价类划分)。
 *
 * 联调时的教训(docs/findings/20260920 附 A):Spring JdkClientHttpRequest 的读超时抛的是
 * java.util.concurrent.TimeoutException 包在 IOException 里,不是 JDK 文档上的 HttpTimeoutException。
 * 这组用例把三种超时异常和它们可能出现的包裹层次都钉住,防止以后改客户端实现时超时又被记成 UPSTREAM_ERROR。
 */
class LlmHttpSupportTest {

    @Test
    @DisplayName("Spring 读超时:ResourceAccessException(IOException(TimeoutException)) → TIMEOUT")
    void springReadTimeoutIsTimeout() {
        RuntimeException e = new ResourceAccessException("I/O error",
                new IOException("Request timed out", new TimeoutException()));
        assertThat(LlmHttpSupport.translate(e).getReason()).isEqualTo(DegradeReason.TIMEOUT);
    }

    @Test
    @DisplayName("JDK HttpTimeoutException / HttpConnectTimeoutException → TIMEOUT")
    void jdkTimeoutsAreTimeout() {
        assertThat(LlmHttpSupport.translate(new ResourceAccessException("x", new HttpTimeoutException("t"))).getReason())
                .isEqualTo(DegradeReason.TIMEOUT);
        assertThat(LlmHttpSupport.translate(new ResourceAccessException("x", new HttpConnectTimeoutException("t"))).getReason())
                .isEqualTo(DegradeReason.TIMEOUT);
    }

    @Test
    @DisplayName("SocketTimeoutException(SimpleClientHttpRequestFactory 路径)→ TIMEOUT")
    void socketTimeoutIsTimeout() {
        assertThat(LlmHttpSupport.translate(new ResourceAccessException("x", new SocketTimeoutException("read"))).getReason())
                .isEqualTo(DegradeReason.TIMEOUT);
    }

    @Test
    @DisplayName("连接被拒 / EOF 这类非超时的 I/O 错误 → UPSTREAM_ERROR,消息带根因")
    void otherIoErrorsAreUpstream() {
        LlmException e = LlmHttpSupport.translate(new ResourceAccessException("x", new IOException("EOF reached while reading")));
        assertThat(e.getReason()).isEqualTo(DegradeReason.UPSTREAM_ERROR);
        assertThat(e.getMessage()).contains("EOF reached");
    }

    @Test
    @DisplayName("HTTP 5xx / 4xx → UPSTREAM_ERROR,消息带状态码")
    void httpErrorsAreUpstream() {
        LlmException server = LlmHttpSupport.translate(HttpServerErrorException.create(HttpStatus.INTERNAL_SERVER_ERROR, "500", null, null, null));
        assertThat(server.getReason()).isEqualTo(DegradeReason.UPSTREAM_ERROR);
        assertThat(server.getMessage()).contains("500");
        LlmException client = LlmHttpSupport.translate(HttpClientErrorException.create(HttpStatus.UNAUTHORIZED, "401", null, null, null));
        assertThat(client.getReason()).isEqualTo(DegradeReason.UPSTREAM_ERROR);
        assertThat(client.getMessage()).contains("401");
    }

    @Test
    @DisplayName("已经是 LlmException 的原样透传")
    void llmExceptionPassesThrough() {
        LlmException original = new LlmException(DegradeReason.BAD_RESPONSE, "缺字段");
        assertThat(LlmHttpSupport.translate(original)).isSameAs(original);
    }

    @Test
    @DisplayName("其他运行时异常(JSON 解析等)→ BAD_RESPONSE")
    void anythingElseIsBadResponse() {
        LlmException e = LlmHttpSupport.translate(new IllegalStateException("Unexpected token"));
        assertThat(e.getReason()).isEqualTo(DegradeReason.BAD_RESPONSE);
        assertThat(e.getMessage()).contains("Unexpected token");
    }
}
