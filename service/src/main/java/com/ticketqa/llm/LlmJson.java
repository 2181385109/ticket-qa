package com.ticketqa.llm;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectReader;

import java.io.IOException;

/**
 * 模型输出的严格解析(KI-022):**恰好一个 JSON 对象**,前后只允许空白。
 *
 * Jackson 的 readTree 默认读完第一个值就返回,后面的内容不报错、被静默丢弃(FAIL_ON_TRAILING_TOKENS 默认关闭)。
 * 对普通下游 HTTP 服务这无所谓——它不会在响应体里写两个对象;对 LLM 这是漏洞:攻击者诱导模型先复述一段构造好的合法 JSON,
 * 服务就会采用它,而模型自己最后给出的答案被丢掉。第一阶段真实模型上观测到过这个形态(D-004|classify|0)。
 *
 * 两个客户端(真实 / 挡板)共用:挡板的响应体对应真实模型的 content,解析严格程度必须一致,否则挡板上测到的行为不代表线上。
 */
final class LlmJson {

    private LlmJson() {
    }

    /** @throws IOException 不是 JSON、不是对象、或对象后面还有别的内容 */
    static JsonNode readSingleObject(ObjectMapper mapper, String text) throws IOException {
        ObjectReader reader = mapper.reader().with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
        JsonNode node = reader.readTree(text == null ? "" : text);
        if (node == null || !node.isObject()) {
            throw new IOException("不是 JSON 对象");
        }
        return node;
    }
}
