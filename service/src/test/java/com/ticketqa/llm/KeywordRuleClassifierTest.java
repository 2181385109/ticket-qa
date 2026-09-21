package com.ticketqa.llm;

import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 关键词规则——降级路径的确定性分类器。
 *
 * 等价类划分(docs/test-design/03):输入按"命中哪一类关键词"分成 REFUND / BILLING / TECH / 无命中 四个有效类,
 * 再加"同时命中多类"(优先级由表顺序决定)和"空 / null"两个特殊类。
 * 因为它是确定的,这里可以断言精确值——这正是它和 LLM 路径在测试策略上的区别(walkthrough 第 10 节)。
 */
class KeywordRuleClassifierTest {

    private final KeywordRuleClassifier rules = new KeywordRuleClassifier();

    @ParameterizedTest(name = "[{index}] 「{0}」→ {2}/{3}")
    @CsvSource({
            // title,                content,           category, priority
            "申请退款,               订单重复扣款,       REFUND,   P1",   // REFUND 与 BILLING 同时命中 → 表顺序 REFUND 先
            "账单问题,               上月发票不对,       BILLING,  P1",
            "登录报错,               App 打不开,         TECH,     P1",
            "登录报错 紧急,          无法登录,           TECH,     P0",   // 无法登录 命中 P0 词
            "系统崩溃,               所有人都用不了,     TECH,     P0",   // 崩溃 既是 TECH 词也是 P0 词
            "咨询会员权益,           想了解一下,         OTHER,    P2",
            "Refund request,         charged twice,     REFUND,   P1",   // 英文 + 大小写不敏感
            "URGENT: billing error,  x,                 BILLING,  P0",   // 英文 P0 词
            "生产环境问题,           页面 404,          TECH,     P0",   // 生产 → P0
    })
    void classifiesByKeywordTable(String title, String content, TicketCategory category, TicketPriority priority) {
        KeywordRuleClassifier.RuleResult r = rules.classify(title, content);
        assertThat(r.category()).isEqualTo(category);
        assertThat(r.priority()).isEqualTo(priority);
    }

    @Test
    @DisplayName("null / 空输入 → OTHER / P2,不抛异常")
    void nullInputsFallToOther() {
        assertThat(rules.classify(null, null)).isEqualTo(new KeywordRuleClassifier.RuleResult(TicketCategory.OTHER, TicketPriority.P2));
        assertThat(rules.classify("", "")).isEqualTo(new KeywordRuleClassifier.RuleResult(TicketCategory.OTHER, TicketPriority.P2));
    }

    @Test
    @DisplayName("同样的输入永远得到同样的结果(确定性——降级路径可断言精确值的前提)")
    void deterministic() {
        KeywordRuleClassifier.RuleResult a = rules.classify("退款", "重复扣款 紧急");
        KeywordRuleClassifier.RuleResult b = rules.classify("退款", "重复扣款 紧急");
        assertThat(a).isEqualTo(b).isEqualTo(new KeywordRuleClassifier.RuleResult(TicketCategory.REFUND, TicketPriority.P0));
    }

    @Test
    @DisplayName("priorityOf:OTHER 类默认 P2,其他类默认 P1,命中 P0 词一律 P0")
    void priorityOfMatrix() {
        assertThat(rules.priorityOf(TicketCategory.OTHER, "普通咨询")).isEqualTo(TicketPriority.P2);
        assertThat(rules.priorityOf(TicketCategory.BILLING, "普通账单")).isEqualTo(TicketPriority.P1);
        assertThat(rules.priorityOf(TicketCategory.OTHER, "宕机了")).isEqualTo(TicketPriority.P0);
    }
}
