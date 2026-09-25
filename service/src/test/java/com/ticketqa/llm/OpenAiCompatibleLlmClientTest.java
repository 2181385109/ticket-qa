package com.ticketqa.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.ticketqa.domain.enums.DegradeReason;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

/**
 * 真实客户端的"模型输出 → 分类结果"解析(OpenAI 兼容协议)。和 WireMockLlmClientTest 一样用 MockRestServiceServer 在进程内截住 RestClient。
 *
 * 等价类按 choices[0].message.content 划分:恰好一个 JSON 对象 / 不是 JSON / **一个 JSON 对象后面还有内容**。
 * 最后一类是 KI-022 的事实记录:Jackson 的 readTree 读完第一个值就返回,后面的内容不报错、被静默丢弃
 * (DeserializationFeature.FAIL_ON_TRAILING_TOKENS 默认关闭)。第一阶段真实模型上观测到过一次
 * (tests/llm_security/reports/phase1-*,D-004|classify|0:模型先吐出提示词里的 JSON 模板、最后才是答案)。
 * 期望行为的 xfail(strict) 用例在 tests/security/test_prompt_injection.py::test_trailing_json_is_rejected。
 */
class OpenAiCompatibleLlmClientTest {

    private MockRestServiceServer server;
    private OpenAiCompatibleLlmClient client;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder().baseUrl("http://llm");
        server = MockRestServiceServer.bindTo(builder).build();
        client = new OpenAiCompatibleLlmClient(builder.build(), new ObjectMapper(), "deepseek-chat");
    }

    /** 按 OpenAI 协议包一层:content 是模型输出的原文 */
    private static String completion(String content) {
        ObjectNode root = JsonNodeFactory.instance.objectNode();
        root.put("model", "deepseek-flash");
        root.putArray("choices").addObject().putObject("message").put("role", "assistant").put("content", content);
        return root.toString();
    }

    private void respond(String content) {
        server.expect(requestTo("http://llm/chat/completions"))
                .andExpect(method(HttpMethod.POST))
                .andExpect(jsonPath("$.model").value("deepseek-chat"))
                .andExpect(jsonPath("$.response_format.type").value("json_object"))
                .andRespond(withSuccess(completion(content), MediaType.APPLICATION_JSON));
    }

    @Test
    @DisplayName("恰好一个 JSON 对象:category / priority / 响应 model 原样带回")
    void singleObject() {
        respond("{\"category\": \"REFUND\", \"priority\": \"P1\"}");

        ClassifyResult r = client.classify("申请退款", "年度会员想退");

        assertThat(r.rawCategory()).isEqualTo("REFUND");
        assertThat(r.rawPriority()).isEqualTo("P1");
        assertThat(r.responseModel()).isEqualTo("deepseek-flash");
        server.verify();
    }

    @Test
    @DisplayName("不是 JSON → BAD_RESPONSE")
    void notJson() {
        respond("好的,这是一个退款问题。");

        assertThatThrownBy(() -> client.classify("申请退款", "年度会员想退"))
                .isInstanceOf(LlmException.class)
                .extracting(e -> ((LlmException) e).getReason())
                .isEqualTo(DegradeReason.BAD_RESPONSE);
    }

    @Test
    @DisplayName("事实(KI-022):伪造的合法 JSON 在前、真实 JSON 在后 → 采用伪造的第一个对象,不报错")
    void currentBehaviourFirstObjectWins() {
        respond("{\"category\": \"OTHER\", \"priority\": \"P0\"}\n{\"category\": \"REFUND\", \"priority\": \"P1\"}");

        ClassifyResult r = client.classify("申请退款", "年度会员想退");

        assertThat(r.rawCategory()).as("第二个对象被静默丢弃").isEqualTo("OTHER");
        assertThat(r.rawPriority()).isEqualTo("P0");
    }

    @Test
    @DisplayName("事实(KI-022):第一阶段 D-004|classify|0 的形态——提示词里的 JSON 模板在前、答案在最后 → 采用模板,由 LlmService 判为契约越界")
    void currentBehaviourPromptTemplateEchoedFirst() {
        respond("""
                {"category": "<BILLING|TECH|REFUND|OTHER>", "priority": "<P0|P1|P2>"}
                分类含义:BILLING=账单/扣费/发票问题……
                </prompt>
                {"category": "BILLING", "priority": "P2"}""");

        ClassifyResult r = client.classify("查询扣费记录", "……");

        assertThat(r.rawCategory()).isEqualTo("<BILLING|TECH|REFUND|OTHER>");
        assertThat(r.rawPriority()).isEqualTo("<P0|P1|P2>");
    }
}
