package com.ticketqa.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketqa.domain.enums.DegradeReason;
import org.springframework.http.MediaType;
import org.springframework.web.client.RestClient;

import java.util.Map;

/**
 * 挡板实现:调 WireMock 容器上的简化契约(ADR-009)
 *   POST /mock/llm/classify {"title","content"}            → {"model","category","priority"}
 *   POST /mock/llm/draft    {"title","content","category"} → {"model","draft"}
 *
 * 故意不复用 OpenAI 协议:挡板的职责是"可控地制造行为"(慢、错、越界),
 * 契约越简单,ops/wiremock/mappings 里的桩越好读、越好改。
 * 桩通过标题里的标记触发故障:[SLOW] [ERROR] [BAD_CATEGORY] [BAD_JSON]。
 */
public class WireMockLlmClient implements LlmClient {

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String model;

    public WireMockLlmClient(RestClient restClient, ObjectMapper objectMapper, String model) {
        this.restClient = restClient;
        this.objectMapper = objectMapper;
        this.model = model;
    }

    @Override
    public String requestModel() {
        return model;
    }

    @Override
    public ClassifyResult classify(String title, String content) {
        JsonNode root = post("/mock/llm/classify", Map.of("title", title, "content", content));
        return new ClassifyResult(
                root.path("category").asText(null),
                root.path("priority").asText(null),
                root.path("model").asText(null));
    }

    @Override
    public DraftResult draftReply(String title, String content, String category) {
        JsonNode root = post("/mock/llm/draft", Map.of("title", title, "content", content, "category", category));
        JsonNode draft = root.path("draft");
        if (draft.isMissingNode() || draft.isNull()) {
            throw new LlmException(DegradeReason.BAD_RESPONSE, "挡板响应缺少 draft 字段");
        }
        return new DraftResult(draft.asText(), root.path("model").asText(null));
    }

    private JsonNode post(String path, Map<String, String> body) {
        try {
            String raw = restClient.post()
                    .uri(path)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(String.class);
            return objectMapper.readTree(raw);
        } catch (RuntimeException e) {
            throw LlmHttpSupport.translate(e);
        } catch (Exception e) {
            throw new LlmException(DegradeReason.BAD_RESPONSE, "挡板响应不是合法 JSON", e);
        }
    }
}
