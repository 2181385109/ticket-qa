package com.ticketqa.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketqa.domain.enums.DegradeReason;
import org.springframework.http.MediaType;
import org.springframework.web.client.RestClient;

import java.util.List;
import java.util.Map;

/**
 * 真实调用:OpenAI 兼容的 /chat/completions 协议(DeepSeek、OpenAI、通义等都能接)。
 * 分类场景要求模型只回 JSON:{"category": "...", "priority": "..."};
 * 用 response_format=json_object + temperature=0 尽量压低随机性,但"尽量"不等于"保证",
 * 契约校验仍然在 LlmService 里做——这正是 LLM 依赖和普通 HTTP 依赖的区别(walkthrough 第 10 节)。
 *
 * 第二阶段(ADR-024)这一层加了两件事:用户文本经 UntrustedInput 装进 <ticket> 数据区(输入隔离,提示词见 LlmPrompts);
 * content 必须恰好是一个 JSON 对象(LlmJson,KI-022)——多出来的任何东西都判 BAD_RESPONSE,而不是只取第一个对象。
 */
public class OpenAiCompatibleLlmClient implements LlmClient {

    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final String model;

    public OpenAiCompatibleLlmClient(RestClient restClient, ObjectMapper objectMapper, String model) {
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
        JsonNode root = chat(LlmPrompts.CLASSIFY_SYSTEM_PROMPT, UntrustedInput.classifyMessage(title, content), true);
        String text = firstContent(root);
        try {
            JsonNode parsed = LlmJson.readSingleObject(objectMapper, text);
            return new ClassifyResult(
                    parsed.path("category").asText(null),
                    parsed.path("priority").asText(null),
                    root.path("model").asText(null));
        } catch (Exception e) {
            throw new LlmException(DegradeReason.BAD_RESPONSE, "分类结果不是恰好一个 JSON 对象: " + abbreviate(text), e);
        }
    }

    @Override
    public DraftResult draftReply(String title, String content, String category) {
        JsonNode root = chat(LlmPrompts.DRAFT_SYSTEM_PROMPT, UntrustedInput.draftMessage(category, title, content), false);
        return new DraftResult(firstContent(root).trim(), root.path("model").asText(null));
    }

    private JsonNode chat(String systemPrompt, String userPrompt, boolean jsonMode) {
        Map<String, Object> body = jsonMode
                ? Map.of("model", model, "temperature", 0, "max_tokens", 200,
                        "response_format", Map.of("type", "json_object"),
                        "messages", messages(systemPrompt, userPrompt))
                : Map.of("model", model, "temperature", 0.3, "max_tokens", 300,
                        "messages", messages(systemPrompt, userPrompt));
        try {
            String raw = restClient.post()
                    .uri("/chat/completions")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(String.class);
            return objectMapper.readTree(raw);
        } catch (RuntimeException e) {
            throw LlmHttpSupport.translate(e);
        } catch (Exception e) {
            throw new LlmException(DegradeReason.BAD_RESPONSE, "LLM 响应体解析失败", e);
        }
    }

    private static List<Map<String, String>> messages(String system, String user) {
        return List.of(Map.of("role", "system", "content", system), Map.of("role", "user", "content", user));
    }

    private static String firstContent(JsonNode root) {
        JsonNode content = root.path("choices").path(0).path("message").path("content");
        if (content.isMissingNode() || content.isNull()) {
            throw new LlmException(DegradeReason.BAD_RESPONSE, "响应缺少 choices[0].message.content");
        }
        return content.asText();
    }

    private static String abbreviate(String s) {
        if (s == null) {
            return "null";
        }
        return s.length() > 120 ? s.substring(0, 120) + "..." : s;
    }
}
