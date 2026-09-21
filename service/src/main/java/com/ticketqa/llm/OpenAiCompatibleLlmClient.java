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
 */
public class OpenAiCompatibleLlmClient implements LlmClient {

    private static final String CLASSIFY_SYSTEM_PROMPT = """
            你是客服工单分类器。根据用户工单的标题和内容,输出严格的 JSON 对象,不要输出任何其他文字:
            {"category": "<BILLING|TECH|REFUND|OTHER>", "priority": "<P0|P1|P2>"}
            分类含义:BILLING=账单/扣费/发票问题,TECH=技术故障/无法使用,REFUND=退款/退货,OTHER=其他。
            优先级:P0=影响使用且紧急,P1=一般问题,P2=咨询建议类。
            """;

    private static final String DRAFT_SYSTEM_PROMPT = """
            你是客服坐席助理。根据工单标题、内容和分类,写一段 80 字以内、礼貌专业的中文回复草稿,
            承认问题、说明正在处理、不要做出无法兑现的承诺。直接输出草稿正文。
            """;

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
        JsonNode root = chat(CLASSIFY_SYSTEM_PROMPT, "标题:" + title + "\n内容:" + content, true);
        String text = firstContent(root);
        try {
            JsonNode parsed = objectMapper.readTree(text);
            return new ClassifyResult(
                    parsed.path("category").asText(null),
                    parsed.path("priority").asText(null),
                    root.path("model").asText(null));
        } catch (Exception e) {
            throw new LlmException(DegradeReason.BAD_RESPONSE, "分类结果不是合法 JSON: " + abbreviate(text), e);
        }
    }

    @Override
    public DraftResult draftReply(String title, String content, String category) {
        JsonNode root = chat(DRAFT_SYSTEM_PROMPT,
                "分类:" + category + "\n标题:" + title + "\n内容:" + content, false);
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
