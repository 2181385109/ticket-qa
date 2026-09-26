package com.ticketqa.llm;

import com.ticketqa.config.LlmProperties;
import com.ticketqa.domain.entity.LlmCallLog;
import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.LlmScene;
import com.ticketqa.domain.enums.ReviewReason;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;

/**
 * LLM 路径的韧性外壳(CLAUDE.md §5.5 的契约全在这一层):
 *
 *   熔断器打开?──是──▶ 直接走规则(CIRCUIT_OPEN)
 *        │否
 *   调 LlmClient ──失败(超时/5xx/解析失败)──▶ 熔断器计数 ──▶ 走规则(reason=失败原因)
 *        │            └─ 输出夹带内容(MIXED_OUTPUT):同样走规则,但**不计数**(DegradeReason.countsTowardCircuit)
 *        │成功
 *   契约校验:category 越界 → 打点 + 落 OTHER;priority 越界 → 打点 + 规则兜底
 *        │
 *   交叉校验(ADR-024 v2):和规则冲突 → 只标 needsReview,仍采用模型结果    草稿:输出检查命中 → 模板(UNSAFE_OUTPUT,不计入熔断)
 *        │
 *   落盘 llm_call_log + 打指标
 *
 * 两个实现(真实 / 挡板)共用这一层,所以挡板制造的 [SLOW] [ERROR] 走的是和线上完全相同的降级代码。
 */
@Service
public class LlmService {

    private static final Logger log = LoggerFactory.getLogger(LlmService.class);

    private final LlmClient client;
    private final KeywordRuleClassifier rules;
    private final LlmCallLogService callLogService;
    private final LlmMetrics metrics;
    private final CircuitBreaker breaker;
    private final Clock clock;
    private final DraftOutputPolicy draftPolicy = DraftOutputPolicy.forDraftPrompt();

    public LlmService(LlmClient client, KeywordRuleClassifier rules, LlmCallLogService callLogService,
                      LlmMetrics metrics, LlmProperties props, Clock clock) {
        this.client = client;
        this.rules = rules;
        this.callLogService = callLogService;
        this.metrics = metrics;
        this.clock = clock;
        this.breaker = new CircuitBreaker(props.circuit().failureThreshold(),
                Duration.ofSeconds(props.circuit().openSeconds()).toMillis(), clock);
        metrics.registerCircuitGauge(() -> breaker.isOpen() ? 1 : 0);
    }

    public ClassifyOutcome classify(String title, String content) {
        LlmScene scene = LlmScene.CLASSIFY;
        if (breaker.isOpen()) {
            return classifyFallback(title, content, DegradeReason.CIRCUIT_OPEN, 0, null);
        }
        long start = clock.millis();
        ClassifyResult result;
        try {
            result = client.classify(title, content);
        } catch (LlmException e) {
            long latency = clock.millis() - start;
            onFailure(scene, e, latency);
            return classifyFallback(title, content, e.getReason(), latency, null);
        }
        long latency = clock.millis() - start;
        breaker.recordSuccess();
        metrics.callDuration(scene, "success", Duration.ofMillis(latency));

        // ---- 契约校验:LLM 说什么不算数,枚举说了算 ----
        Optional<TicketCategory> parsedCategory = TicketCategory.parse(result.rawCategory());
        boolean violated = parsedCategory.isEmpty();
        TicketCategory modelCategory = parsedCategory.orElse(TicketCategory.OTHER);
        if (violated) {
            metrics.contractViolation(scene, "category");
            log.warn("LLM 分类越界 raw={} → OTHER", result.rawCategory());
        }
        Optional<TicketPriority> parsedPriority = TicketPriority.parse(result.rawPriority());
        TicketPriority priority = parsedPriority.orElseGet(() -> {
            metrics.contractViolation(scene, "priority");
            log.warn("LLM 优先级越界 raw={} → 规则兜底", result.rawPriority());
            return rules.priorityOf(modelCategory, lower(title, content));
        });
        boolean anyViolation = violated || parsedPriority.isEmpty();

        // ---- 交叉校验(ADR-024):注入能改变模型的判断,改变不了关键词规则的判断 ----
        // 只比对模型合法给出的字段:越界字段已经走了上面的契约路径,不再参与
        KeywordRuleClassifier.RuleResult rule = rules.classify(title, content);
        Set<ReviewReason> conflicts = ClassifyCrossCheck.check(
                violated ? null : modelCategory, parsedPriority.orElse(null), rule.priority(),
                rules.matchedCategories(title, content));
        // v2(ADR-024 修订 #4,KI-023):冲突只标记、不改采用值。规则 P2 里混着"认出是咨询"和"什么都没认出",
        // 它没有资格推翻模型——v1 用规则结果覆盖,把不含关键词的真 P0 降成了 P2
        boolean needsReview = !conflicts.isEmpty();
        TicketCategory category = modelCategory;
        if (needsReview) {
            conflicts.forEach(metrics::review);
            log.warn("LLM 分类与规则冲突 {} model={}/{} rule={}/{} → 保留模型结果,标记人工复核",
                    conflicts, modelCategory, priority, rule.category(), rule.priority());
        }
        String reviewReason = ClassifyCrossCheck.join(conflicts);

        LlmCallLog entry = buildLog(scene, null, result.responseModel(), latency,
                false, null, result.rawCategory(), category, anyViolation);
        entry.setNeedsReview(needsReview);
        entry.setReviewReason(reviewReason);
        entry.setRuleCategory(rule.category());
        entry.setRulePriority(rule.priority());
        Long logId = callLogService.record(entry);
        return new ClassifyOutcome(category, priority, false, null, client.requestModel(),
                result.responseModel(), latency, anyViolation, result.rawCategory(), logId, needsReview, reviewReason);
    }

    public DraftOutcome draftReply(Long ticketId, String title, String content, TicketCategory category) {
        LlmScene scene = LlmScene.DRAFT_REPLY;
        if (breaker.isOpen()) {
            return draftFallback(ticketId, title, category, DegradeReason.CIRCUIT_OPEN, 0, null, null);
        }
        long start = clock.millis();
        DraftResult result;
        try {
            result = client.draftReply(title, content, category.name());
        } catch (LlmException e) {
            long latency = clock.millis() - start;
            onFailure(scene, e, latency);
            return draftFallback(ticketId, title, category, e.getReason(), latency, null, null);
        }
        long latency = clock.millis() - start;
        // 调用本身成功了:先记成功再做输出检查——检查命中是防御动作不是故障,不能计入熔断(否则 5 次注入草稿即可熔断全站)
        breaker.recordSuccess();
        metrics.callDuration(scene, "success", Duration.ofMillis(latency));

        Set<ReviewReason> unsafe = draftPolicy.check(result.draft());
        if (!unsafe.isEmpty()) {
            unsafe.forEach(metrics::review);
            log.warn("LLM 草稿输出检查命中 {} → 换成模板草稿", unsafe);
            return draftFallback(ticketId, title, category, DegradeReason.UNSAFE_OUTPUT, latency,
                    result.responseModel(), ClassifyCrossCheck.join(unsafe));
        }
        Long logId = callLogService.record(buildLog(scene, ticketId, result.responseModel(), latency,
                false, null, null, null, false));
        return new DraftOutcome(result.draft(), false, null, client.requestModel(), result.responseModel(), latency, logId);
    }

    public CircuitBreaker breaker() {
        return breaker;
    }

    // ---------------------------------------------------------------- 内部

    private void onFailure(LlmScene scene, LlmException e, long latencyMs) {
        metrics.callDuration(scene, "failure_" + e.getReason().name().toLowerCase(Locale.ROOT), Duration.ofMillis(latencyMs));
        if (!e.getReason().countsTowardCircuit()) {
            // MIXED_OUTPUT:上游答了、答案夹带了东西。和 UNSAFE_OUTPUT 同理记成功——攻击者能诱导出的输出不能成为熔断开关
            breaker.recordSuccess();
            log.warn("LLM 输出不可用但不计入熔断 scene={} reason={} latency={}ms msg={}",
                    scene, e.getReason(), latencyMs, e.getMessage());
            return;
        }
        boolean tripped = breaker.recordFailure();
        log.warn("LLM 调用失败 scene={} reason={} latency={}ms consecutiveFailures={} msg={}",
                scene, e.getReason(), latencyMs, breaker.consecutiveFailures(), e.getMessage());
        if (tripped) {
            metrics.circuitOpened(scene);
            log.error("LLM 熔断打开,至 {} 前所有调用直接走规则",
                    java.time.LocalDateTime.ofInstant(breaker.openUntil(), clock.getZone()));
        }
    }

    private ClassifyOutcome classifyFallback(String title, String content, DegradeReason reason, long latencyMs, String rawCategory) {
        KeywordRuleClassifier.RuleResult rule = rules.classify(title, content);
        metrics.fallback(LlmScene.CLASSIFY, reason);
        LlmCallLog entry = buildLog(LlmScene.CLASSIFY, null, null, latencyMs, true, reason, rawCategory, rule.category(), false);
        entry.setRuleCategory(rule.category());
        entry.setRulePriority(rule.priority());
        Long logId = callLogService.record(entry);
        log.info("LLM 分类降级 reason={} → 规则 category={} priority={}", reason, rule.category(), rule.priority());
        return new ClassifyOutcome(rule.category(), rule.priority(), true, reason, client.requestModel(),
                null, latencyMs, false, rawCategory, logId);
    }

    /**
     * @param responseModel UNSAFE_OUTPUT 时模型是回答了的,如实记下响应模型名;其余降级没有响应,传 null
     * @param reviewReason  UNSAFE_OUTPUT 时记下命中的是哪条检查(UNSAFE_PROMISE / UNSAFE_LEAK)
     */
    private DraftOutcome draftFallback(Long ticketId, String title, TicketCategory category, DegradeReason reason, long latencyMs,
                                       String responseModel, String reviewReason) {
        metrics.fallback(LlmScene.DRAFT_REPLY, reason);
        LlmCallLog entry = buildLog(LlmScene.DRAFT_REPLY, ticketId, responseModel, latencyMs, true, reason, null, category, false);
        entry.setReviewReason(reviewReason);
        Long logId = callLogService.record(entry);
        String template = "您好,我们已收到您关于「" + title + "」的反馈(" + category + " 类),正在核实处理中,会尽快给您答复。";
        return new DraftOutcome(template, true, reason, client.requestModel(), responseModel, latencyMs, logId);
    }

    private LlmCallLog buildLog(LlmScene scene, Long ticketId, String responseModel, long latencyMs,
                                boolean degraded, DegradeReason reason, String rawCategory,
                                TicketCategory finalCategory, boolean contractViolated) {
        LlmCallLog entry = new LlmCallLog();
        entry.setTicketId(ticketId);
        entry.setScene(scene);
        entry.setRequestModel(client.requestModel());
        entry.setResponseModel(responseModel);
        entry.setLatencyMs((int) Math.min(latencyMs, Integer.MAX_VALUE));
        entry.setDegraded(degraded);
        entry.setDegradeReason(reason);
        entry.setRawCategory(rawCategory);
        entry.setFinalCategory(finalCategory);
        entry.setContractViolated(contractViolated);
        entry.setNeedsReview(false);
        return entry;
    }

    private static String lower(String title, String content) {
        return ((title == null ? "" : title) + " " + (content == null ? "" : content)).toLowerCase(Locale.ROOT);
    }
}
