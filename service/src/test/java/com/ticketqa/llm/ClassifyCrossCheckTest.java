package com.ticketqa.llm;

import com.ticketqa.domain.enums.ReviewReason;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

import java.util.EnumSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static com.ticketqa.domain.enums.TicketCategory.BILLING;
import static com.ticketqa.domain.enums.TicketCategory.OTHER;
import static com.ticketqa.domain.enums.TicketCategory.REFUND;
import static com.ticketqa.domain.enums.TicketCategory.TECH;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * 交叉校验阈值(ADR-024,第一阶段开跑前冻结)。判定表:test-design/03 R9~R14。
 *
 * 优先级维度只有一条会冲突的格子——模型 P0 × 规则 P2,其余 8 格全部放行;用 3×3 全组合的参数化用例把"差一档不冲突"钉死,
 * 否则将来有人把条件改成"不一致就复核",会把所有不含"紧急 / 宕机"字样的真 P0 都拦下来,而没有任何用例变红。
 */
class ClassifyCrossCheckTest {

    private static final Set<TicketCategory> NONE = Set.of();

    @ParameterizedTest(name = "[{index}] 模型 {0} × 规则 {1} → 冲突 {2}")
    @CsvSource({
            "P0, P0, false", "P0, P1, false", "P0, P2, true",
            "P1, P0, false", "P1, P1, false", "P1, P2, false",
            "P2, P0, false", "P2, P1, false", "P2, P2, false"})
    @DisplayName("优先级:只有模型 P0 且规则 P2(差两档)才冲突")
    void priorityGrid(TicketPriority model, TicketPriority rule, boolean conflict) {
        Set<ReviewReason> r = ClassifyCrossCheck.check(OTHER, model, rule, NONE);
        assertThat(r.contains(ReviewReason.PRIORITY_CONFLICT)).isEqualTo(conflict);
    }

    @ParameterizedTest(name = "[{index}] 规则命中 {0},模型 {1} → 冲突 {2}")
    @CsvSource({
            "'',               TECH,    false",   // 规则一个关键词都没命中:没有证据,不算冲突
            "REFUND,           TECH,    true",
            "REFUND,           REFUND,  false",
            "REFUND,           OTHER,   true",    // 规则明明看到退款词,模型却说"其他"
            "REFUND BILLING,   BILLING, false",   // 命中多个类别,模型选哪个都有依据
            "REFUND BILLING,   TECH,    true"})
    @DisplayName("分类:规则命中 ≥1 类,且模型类别不在命中集合里才冲突")
    void categoryTable(String matched, TicketCategory model, boolean conflict) {
        Set<TicketCategory> set = new LinkedHashSet<>();
        for (String c : matched.trim().split("\\s+")) {
            if (!c.isEmpty()) {
                set.add(TicketCategory.valueOf(c));
            }
        }
        Set<ReviewReason> r = ClassifyCrossCheck.check(model, TicketPriority.P1, TicketPriority.P1, set);
        assertThat(r.contains(ReviewReason.CATEGORY_CONFLICT)).isEqualTo(conflict);
    }

    @Test
    @DisplayName("越界字段不参与比对:category 越界(传 null)时即使规则命中 REFUND 也不报分类冲突;priority 越界同理")
    void violatedFieldsAreSkipped() {
        assertThat(ClassifyCrossCheck.check(null, TicketPriority.P1, TicketPriority.P1, Set.of(REFUND))).isEmpty();
        assertThat(ClassifyCrossCheck.check(REFUND, null, TicketPriority.P2, Set.of(REFUND))).isEmpty();
    }

    @Test
    @DisplayName("两个维度同时冲突 → 两个原因都记,按枚举顺序连接")
    void bothConflicts() {
        Set<ReviewReason> r = ClassifyCrossCheck.check(TECH, TicketPriority.P0, TicketPriority.P2, Set.of(BILLING));
        assertThat(r).containsExactly(ReviewReason.PRIORITY_CONFLICT, ReviewReason.CATEGORY_CONFLICT);
        assertThat(ClassifyCrossCheck.join(r)).isEqualTo("PRIORITY_CONFLICT,CATEGORY_CONFLICT");
        assertThat(ClassifyCrossCheck.join(EnumSet.noneOf(ReviewReason.class))).isNull();
    }

    @Nested
    @DisplayName("规则命中集合 KeywordRuleClassifier.matchedCategories")
    class Matched {

        private final KeywordRuleClassifier rules = new KeywordRuleClassifier();

        @Test
        @DisplayName("按规则表顺序返回全部命中类别;classify 只取第一个")
        void allMatchesInOrder() {
            assertThat(rules.matchedCategories("账单有误", "重复扣费了想退款,App 还闪退"))
                    .containsExactly(REFUND, BILLING, TECH);
            assertThat(rules.classify("账单有误", "重复扣费了想退款,App 还闪退").category()).isEqualTo(REFUND);
        }

        @Test
        @DisplayName("没有任何关键词 → 空集合(classify 给 OTHER,但 OTHER 不是命中)")
        void noMatch() {
            assertThat(rules.matchedCategories("客服周末上班吗", "想问下值班时间")).isEmpty();
            assertThat(rules.matchedCategories(null, null)).isEmpty();
        }

        @Test
        @DisplayName("大小写不敏感,与 classify 一致")
        void caseInsensitive() {
            assertThat(List.copyOf(rules.matchedCategories("REFUND please", ""))).containsExactly(REFUND);
        }
    }
}
