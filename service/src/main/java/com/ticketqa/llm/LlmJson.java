package com.ticketqa.llm;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.core.JsonToken;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketqa.domain.enums.DegradeReason;

import java.io.IOException;

/**
 * 模型输出的严格解析(KI-022):**恰好一个 JSON 对象**,前后只允许空白。
 *
 * Jackson 的 readTree 默认读完第一个值就返回,后面的内容不报错、被静默丢弃(FAIL_ON_TRAILING_TOKENS 默认关闭)。
 * 对普通下游 HTTP 服务这无所谓——它不会在响应体里写两个对象;对 LLM 这是漏洞:攻击者诱导模型先复述一段构造好的合法 JSON,
 * 服务就会采用它,而模型自己最后给出的答案被丢掉。第一阶段真实模型上观测到过这个形态(D-004|classify|0)。
 *
 * 不合格的输出再分两种,因为它们对熔断器的意义相反(ADR-024 "严格解析与熔断"):
 *   - 文本里某处读得出一个完整的 JSON 对象 → MIXED_OUTPUT:上游健康、回答被攻击者带偏了,不计入熔断;
 *   - 一个完整对象都读不出来            → BAD_RESPONSE:输出格式整体崩坏,照旧计入熔断(ADR-004)。
 *
 * 两个客户端(真实 / 挡板)共用:挡板的响应体对应真实模型的 content,解析严格程度必须一致,否则挡板上测到的行为不代表线上。
 */
final class LlmJson {

    private static final int MESSAGE_PREVIEW = 120;

    private LlmJson() {
    }

    /** @throws LlmException reason 为 MIXED_OUTPUT 或 BAD_RESPONSE,区分见类注释 */
    static JsonNode readSingleObject(ObjectMapper mapper, String text) {
        String s = text == null ? "" : text;
        try {
            JsonNode node = mapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS).readTree(s);
            if (node != null && node.isObject()) {
                return node;
            }
        } catch (IOException notExactlyOneValue) {
            // 落到下面判断是哪一种不合格
        }
        if (containsCompleteObject(mapper, s)) {
            throw new LlmException(DegradeReason.MIXED_OUTPUT, "输出含 JSON 对象但不是恰好一个对象: " + preview(s));
        }
        throw new LlmException(DegradeReason.BAD_RESPONSE, "输出里读不出任何完整的 JSON 对象: " + preview(s));
    }

    /**
     * 从每个 '{' 起试读一个完整对象(skipChildren 会一路校验语法直到配对的 '}')。
     * 模型输出受 max_tokens 限制(分类 200),最坏 O(n²) 也只有几万次字符比较,不值得写更聪明的扫描。
     */
    static boolean containsCompleteObject(ObjectMapper mapper, String s) {
        char[] chars = s.toCharArray();
        for (int i = s.indexOf('{'); i >= 0; i = s.indexOf('{', i + 1)) {
            try (JsonParser p = mapper.getFactory().createParser(chars, i, chars.length - i)) {
                if (p.nextToken() == JsonToken.START_OBJECT) {
                    p.skipChildren();
                    return true;
                }
            } catch (IOException notAnObjectHere) {
                // 这个 '{' 起读不出完整对象,试下一个
            }
        }
        return false;
    }

    private static String preview(String s) {
        return s.length() > MESSAGE_PREVIEW ? s.substring(0, MESSAGE_PREVIEW) + "..." : s;
    }
}
