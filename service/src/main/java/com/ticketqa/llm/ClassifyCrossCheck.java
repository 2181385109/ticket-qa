package com.ticketqa.llm;

import com.ticketqa.domain.enums.ReviewReason;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;

import java.util.EnumSet;
import java.util.Set;

/**
 * 分类交叉校验(ADR-024"交叉校验阈值",第一阶段开跑前冻结):模型结果和关键词规则的结果比对,冲突时标记人工复核。
 * 冲突时怎么处理不在这里决定:v1 改用规则结果,v2(修订 #4,KI-023)只标记、仍采用模型结果——见 LlmService.classify。
 *
 * 为什么能发现注入:注入改变的是模型的判断,改变不了规则的判断——规则只看关键词,不"听"任何指令。
 * 为什么阈值是这两条(而不是"不一致就复核"):规则的 P1 是"有类别关键词、没有紧急词"时的默认值,表示规则没意见;
 * 规则的 P2 只在一个类别关键词都没命中时出现,是它能给出的最强的"这不紧急"。所以只有"模型 P0 且规则 P2"才是真冲突。
 * 分类同理:规则一个类别都没命中时没有证据;命中多个类别时模型选哪个都有依据。
 *
 * 纯函数,不依赖 Spring:判定表的每一行都能直接写成一条单测(ClassifyCrossCheckTest)。
 */
public final class ClassifyCrossCheck {

    private ClassifyCrossCheck() {
    }

    /**
     * @param modelCategory 模型给出且在枚举内的类别;越界(已落 OTHER)时传 null——越界字段走原契约路径,不参与比对
     * @param modelPriority 模型给出且在枚举内的优先级;越界时传 null
     * @param rulePriority  规则对同一段文本给出的优先级
     * @param matched       规则命中的全部类别(KeywordRuleClassifier.matchedCategories)
     * @return 冲突原因;空集合 = 不冲突
     */
    public static Set<ReviewReason> check(TicketCategory modelCategory, TicketPriority modelPriority,
                                          TicketPriority rulePriority, Set<TicketCategory> matched) {
        Set<ReviewReason> reasons = EnumSet.noneOf(ReviewReason.class);
        if (modelPriority == TicketPriority.P0 && rulePriority == TicketPriority.P2) {
            reasons.add(ReviewReason.PRIORITY_CONFLICT);
        }
        if (modelCategory != null && !matched.isEmpty() && !matched.contains(modelCategory)) {
            reasons.add(ReviewReason.CATEGORY_CONFLICT);
        }
        return reasons;
    }

    /** 逗号连接,按枚举声明顺序——落库和响应里的字符串是确定的 */
    public static String join(Set<ReviewReason> reasons) {
        return reasons.isEmpty() ? null : String.join(",", reasons.stream().map(Enum::name).toList());
    }
}
