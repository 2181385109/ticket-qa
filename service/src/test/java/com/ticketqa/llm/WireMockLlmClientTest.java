package com.ticketqa.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketqa.domain.enums.DegradeReason;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * 挡板客户端的"请求怎么发、响应怎么解析"(ADR-009 的契约)。
 *
 * 用 Spring 自带的 MockRestServiceServer 在进程内截住 RestClient(ADR-013):不起 WireMock 容器,
 * 也不走真实 socket——所以这里测不到超时和 h2c 这类传输层问题,那些留给接口自动化对着真容器测。
 * 这一层的等价类:响应 2xx 且字段齐全 / 2xx 但缺字段 / 2xx 但不是 JSON / 非 2xx。
 */
class WireMockLlmClientTest {

    private MockRestServiceServer server;
    private WireMockLlmClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("http://mock");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new WireMockLlmClient(builder.build(), new ObjectMapper(), "mock-classifier-v1");
    }

    @Test
    @DisplayName("classify:POST /mock/llm/classify,JSON 体带 title/content;响应的 category/priority/model 原样返回(不做枚举判断)")
    void classifyHappyPath() {
        server.expect(requestTo("http://mock/mock/llm/classify"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.title").value("申请退款"))
                .andExpect(jsonPath("$.content").value("重复扣款"))
                .andRespond(withSuccess("{\"model\":\"mock-classifier-v1\",\"category\":\"SPAM\",\"priority\":\"P1\"}", MediaType.APPLICATION_JSON));

        ClassifyResult r = client.classify("申请退款", "重复扣款");

        assertThat(r.rawCategory()).as("客户端不替 LlmService 做主,越界值原样带回").isEqualTo("SPAM");
        assertThat(r.rawPriority()).isEqualTo("P1");
        assertThat(r.responseModel()).isEqualTo("mock-classifier-v1");
        assertThat(client.requestModel()).isEqualTo("mock-classifier-v1");
        server.verify();
    }

    @Test
    @DisplayName("classify:响应缺 category 字段 → rawCategory 为 null(由上层按越界处理)")
    void classifyMissingFieldsBecomeNull() {
        server.expect(requestTo("http://mock/mock/llm/classify"))
                .andRespond(withSuccess("{\"model\":\"m\"}", MediaType.APPLICATION_JSON));
        ClassifyResult r = client.classify("t", "c");
        assertThat(r.rawCategory()).isNull();
        assertThat(r.rawPriority()).isNull();
    }

    @Test
    @DisplayName("响应体不是 JSON → BAD_RESPONSE")
    void nonJsonBodyIsBadResponse() {
        server.expect(requestTo("http://mock/mock/llm/classify"))
                .andRespond(withSuccess("I am not JSON", MediaType.TEXT_PLAIN));
        assertThatThrownBy(() -> client.classify("t", "c"))
                .isInstanceOf(LlmException.class)
                .extracting(e -> ((LlmException) e).getReason()).isEqualTo(DegradeReason.BAD_RESPONSE);
    }

    @Test
    @DisplayName("HTTP 500 → UPSTREAM_ERROR")
    void serverErrorIsUpstream() {
        server.expect(requestTo("http://mock/mock/llm/classify")).andRespond(withServerError());
        assertThatThrownBy(() -> client.classify("t", "c"))
                .isInstanceOf(LlmException.class)
                .extracting(e -> ((LlmException) e).getReason()).isEqualTo(DegradeReason.UPSTREAM_ERROR);
    }

    @Test
    @DisplayName("HTTP 429(限流)同样归 UPSTREAM_ERROR")
    void tooManyRequestsIsUpstream() {
        server.expect(requestTo("http://mock/mock/llm/classify")).andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS));
        assertThatThrownBy(() -> client.classify("t", "c"))
                .extracting(e -> ((LlmException) e).getReason()).isEqualTo(DegradeReason.UPSTREAM_ERROR);
    }

    @Test
    @DisplayName("draftReply:请求体带 category;响应 draft/model 原样返回")
    void draftHappyPath() {
        server.expect(requestTo("http://mock/mock/llm/draft"))
                .andExpect(jsonPath("$.category").value("REFUND"))
                .andRespond(withSuccess("{\"model\":\"mock-writer-v1\",\"draft\":\"您好\"}", MediaType.APPLICATION_JSON));
        DraftResult r = client.draftReply("t", "c", "REFUND");
        assertThat(r.draft()).isEqualTo("您好");
        assertThat(r.responseModel()).isEqualTo("mock-writer-v1");
    }

    @Test
    @DisplayName("draftReply:2xx 但缺 draft 字段 → BAD_RESPONSE(草稿没有'越界'一说,缺就是坏)")
    void draftMissingFieldIsBadResponse() {
        server.expect(requestTo("http://mock/mock/llm/draft"))
                .andRespond(withSuccess("{\"model\":\"mock-writer-v1\"}", MediaType.APPLICATION_JSON));
        assertThatThrownBy(() -> client.draftReply("t", "c", "OTHER"))
                .isInstanceOf(LlmException.class)
                .extracting(e -> ((LlmException) e).getReason()).isEqualTo(DegradeReason.BAD_RESPONSE);
    }

    @Test
    @DisplayName("draftReply:draft 为 null → BAD_RESPONSE")
    void draftNullIsBadResponse() {
        server.expect(requestTo("http://mock/mock/llm/draft"))
                .andRespond(withSuccess("{\"model\":\"m\",\"draft\":null}", MediaType.APPLICATION_JSON));
        assertThatThrownBy(() -> client.draftReply("t", "c", "OTHER"))
                .extracting(e -> ((LlmException) e).getReason()).isEqualTo(DegradeReason.BAD_RESPONSE);
    }
}
