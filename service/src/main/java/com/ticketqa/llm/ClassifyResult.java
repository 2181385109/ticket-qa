package com.ticketqa.llm;

/**
 * 客户端返回的原始分类结果。rawCategory / rawPriority 是字符串而不是枚举:
 * 越不越界是 LlmService 的判断,客户端不替它做主。
 */
public record ClassifyResult(String rawCategory, String rawPriority, String responseModel) {
}
