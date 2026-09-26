package com.ticketqa.llm;

import com.ticketqa.domain.enums.ReviewReason;

import java.text.Normalizer;
import java.util.EnumSet;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 草稿输出检查(ADR-024 第二阶段):模型写出的草稿交给坐席之前过两道检查,命中任何一道就换成模板草稿(UNSAFE_OUTPUT)。
 *
 * 1. 越权承诺(C 类):归一化后子串匹配下面的防御词表。**不识别否定句**——"无法承诺全额退款"也会被拦,
 *    代价是坐席少拿到一份草稿(拿到的是模板),而放过一句真承诺的代价是公司对客户的资金 / 法律承诺。
 * 2. 系统提示词泄露(D 类):把草稿系统提示词归一化成只剩文字和数字,取所有长度为 {@link #LEAK_WINDOW} 的连续片段;
 *    草稿(同样归一化)里出现任何一段就算泄露。只删标点、空白,不做同义词——所以"逐字复述""换了标点的复述""改一两个字的复述"
 *    只要还剩 8 个字连续不变就能抓到,换成自己的话讲一遍抓不到(已知局限)。
 *
 * 防御词表和评测用的裁判词表(tests/llm_security/data/judge_promise_keywords.json)**分开维护**,防御表必须是裁判表的子集
 * (tests/llm_security/test_dataset.py 从本文件解析校验)——否则评测会被"防御拦了什么"反过来定义,报告里的"防御词表之外的命中"也就无从说起。
 * 词表与窗口长度都是在第一阶段数据之前、只按攻击手法和提示词文本定的,没有用第一阶段的草稿调过(防过拟合,计划 §2-8)。
 */
public final class DraftOutputPolicy {

    /** 泄露检测窗口:8 个连续文字。依据见类注释与 ADR-024 */
    static final int LEAK_WINDOW = 8;

    // PROMISE_WORDS_BEGIN(test_dataset.py 按这对标记解析,改格式要同步改那边)
    static final List<String> PROMISE_WORDS = List.of(
            // 退款
            "全额退款", "全部退款", "全额退还", "全额退回", "全款退回", "退还全部", "全额退给", "退款已批准", "已为您办理全额", "full refund",
            // 赔偿
            "赔偿", "补偿", "赔付", "compensat",
            // 办结 / 到账时限
            "今天之内", "今天内", "今日内", "当天内", "今天一定", "今天就能", "24小时内", "二十四小时内",
            "立即到账", "马上到账", "立刻到账", "within 24 hours",
            // 保证
            "保证解决", "一定解决", "一定修好", "保证今天", "确保今天", "guarantee");
    // PROMISE_WORDS_END

    private final List<String> promiseWords;
    private final Set<String> promptWindows;

    public DraftOutputPolicy(String protectedPrompt) {
        this.promiseWords = PROMISE_WORDS.stream().map(DraftOutputPolicy::normalize).toList();
        this.promptWindows = windows(lettersOnly(protectedPrompt));
    }

    /** 默认保护草稿系统提示词 */
    public static DraftOutputPolicy forDraftPrompt() {
        return new DraftOutputPolicy(LlmPrompts.DRAFT_SYSTEM_PROMPT);
    }

    /** @return 命中的检查;空集合 = 放行 */
    public Set<ReviewReason> check(String draft) {
        Set<ReviewReason> reasons = EnumSet.noneOf(ReviewReason.class);
        if (draft == null || draft.isEmpty()) {
            return reasons;
        }
        String norm = normalize(draft);
        if (promiseWords.stream().anyMatch(norm::contains)) {
            reasons.add(ReviewReason.UNSAFE_PROMISE);
        }
        String letters = lettersOnly(draft);
        for (int i = 0; i + LEAK_WINDOW <= letters.length(); i++) {
            if (promptWindows.contains(letters.substring(i, i + LEAK_WINDOW))) {
                reasons.add(ReviewReason.UNSAFE_LEAK);
                break;
            }
        }
        return reasons;
    }

    /** NFKC → 小写 → 删空白:全角数字 / 字母、大小写、插空格都不影响匹配(与裁判的归一化一致) */
    static String normalize(String s) {
        String n = Normalizer.normalize(s, Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
        StringBuilder sb = new StringBuilder(n.length());
        n.codePoints().filter(cp -> !Character.isWhitespace(cp)).forEach(sb::appendCodePoint);
        return sb.toString();
    }

    /** 在 normalize 的基础上再删掉所有标点符号,只留文字和数字:复述时换标点("、"→",")不影响泄露检测 */
    static String lettersOnly(String s) {
        StringBuilder sb = new StringBuilder();
        normalize(s).codePoints().filter(Character::isLetterOrDigit).forEach(sb::appendCodePoint);
        return sb.toString();
    }

    private static Set<String> windows(String text) {
        Set<String> set = new HashSet<>();
        for (int i = 0; i + LEAK_WINDOW <= text.length(); i++) {
            set.add(text.substring(i, i + LEAK_WINDOW));
        }
        return set;
    }
}
