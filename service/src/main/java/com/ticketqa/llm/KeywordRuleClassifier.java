package com.ticketqa.llm;

import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 关键词规则分类:LLM 超时 / 熔断 / 出错时的降级路径。
 * 输出是确定的——同样的输入永远得到同样的结果——这一点对测试至关重要:
 * 降级路径的用例可以断言精确值,而 LLM 路径只能断言契约(在枚举内)。
 *
 * 规则表用 LinkedHashMap 保序:先匹配到的类别赢,所以 REFUND 排在 BILLING 前面
 * ("退款账单"归退款)。
 */
@Component
public class KeywordRuleClassifier {

    private static final Map<TicketCategory, List<String>> CATEGORY_KEYWORDS = new LinkedHashMap<>();
    private static final List<String> P0_KEYWORDS = List.of("紧急", "urgent", "无法登录", "崩溃", "全部用户", "生产", "宕机", "crash", "down");

    static {
        CATEGORY_KEYWORDS.put(TicketCategory.REFUND, List.of("退款", "退钱", "退费", "退货", "refund"));
        CATEGORY_KEYWORDS.put(TicketCategory.BILLING, List.of("账单", "扣费", "发票", "计费", "重复扣", "billing", "invoice", "charge"));
        CATEGORY_KEYWORDS.put(TicketCategory.TECH, List.of("报错", "崩溃", "无法登录", "打不开", "闪退", "登录", "bug", "crash", "error", "login", "404", "500"));
    }

    public record RuleResult(TicketCategory category, TicketPriority priority) {
    }

    public RuleResult classify(String title, String content) {
        String text = ((title == null ? "" : title) + " " + (content == null ? "" : content)).toLowerCase(Locale.ROOT);
        TicketCategory category = CATEGORY_KEYWORDS.entrySet().stream()
                .filter(e -> e.getValue().stream().anyMatch(text::contains))
                .map(Map.Entry::getKey)
                .findFirst()
                .orElse(TicketCategory.OTHER);
        return new RuleResult(category, priorityOf(category, text));
    }

    public TicketPriority priorityOf(TicketCategory category, String lowerText) {
        if (P0_KEYWORDS.stream().anyMatch(lowerText::contains)) {
            return TicketPriority.P0;
        }
        return category == TicketCategory.OTHER ? TicketPriority.P2 : TicketPriority.P1;
    }
}
