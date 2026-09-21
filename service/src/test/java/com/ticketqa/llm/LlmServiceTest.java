package com.ticketqa.llm;

import com.ticketqa.domain.entity.LlmCallLog;
import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.LlmScene;
import com.ticketqa.domain.enums.TicketCategory;
import com.ticketqa.domain.enums.TicketPriority;
import com.ticketqa.support.MutableClock;
import com.ticketqa.support.TestFixtures;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.junit.jupiter.api.extension.ExtendWith;

import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.atomic.AtomicLong;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * LLM 韧性外壳(CLAUDE.md §5.5 / ADR-004)。
 *
 * 判定表(docs/test-design/03-LLM降级判定表.md)的条件:
 *   C1 熔断器是否打开   C2 客户端是否抛异常(及原因)   C3 返回的分类是否在枚举内   C4 返回的优先级是否在枚举内
 * 动作:
 *   走规则 / 用 LLM 结果 / 落 OTHER / 打哪个指标 / 落盘记录里 degraded、reason、response_model、raw_category 各是什么
 *
 * 这里 Mock 的是 LlmClient(HTTP 那一层)和 LlmCallLogService(DB 那一层),
 * 熔断器、规则分类器、指标都用真实对象——它们是被测逻辑的一部分。
 * 时间用 MutableClock:超时的耗时、熔断的 60 秒都靠拨表,不 sleep。
 */
@ExtendWith(MockitoExtension.class)
class LlmServiceTest {

    private static final String TITLE = "申请退款";
    private static final String CONTENT = "订单重复扣款";

    @Mock
    private LlmClient client;
    @Mock
    private LlmCallLogService callLogService;

    private MeterRegistry registry;
    private MutableClock clock;
    private LlmService service;
    private final AtomicLong logIds = new AtomicLong();

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        clock = MutableClock.at(Instant.parse("2026-09-20T02:00:00Z"));
        lenient().when(client.requestModel()).thenReturn("mock-classifier-v1");
        // 每次落盘返回一个递增 id,模拟自增主键
        lenient().when(callLogService.record(any())).thenAnswer(inv -> logIds.incrementAndGet());
        service = new LlmService(client, new KeywordRuleClassifier(), callLogService,
                new LlmMetrics(registry), TestFixtures.llmProperties(), clock);
    }

    // ------------------------------------------------------------------ 工具

    private LlmException failing(DegradeReason reason, long costMillis) {
        clock.advance(Duration.ofMillis(costMillis));
        return new LlmException(reason, "模拟失败 " + reason);
    }

    /**
     * 用 doAnswer/doReturn 而不是 when(...).thenX:when(client.classify(...)) 会真的调用一次 classify,
     * 如果上一个桩是"抛异常",重新打桩时就会在 when 里炸掉——熔断恢复用例要在同一个测试里先失败后成功,必须用这种写法。
     */
    private void clientFailsWith(DegradeReason reason, long costMillis) {
        doAnswer(inv -> {
            throw failing(reason, costMillis);
        }).when(client).classify(anyString(), anyString());
    }

    private void clientReturns(String category, String priority) {
        doReturn(new ClassifyResult(category, priority, "mock-classifier-v1"))
                .when(client).classify(anyString(), anyString());
    }

    private double counter(String name, String... tags) {
        return registry.find(name).tags(tags).counter() == null ? 0
                : registry.find(name).tags(tags).counter().count();
    }

    private LlmCallLog lastLog() {
        ArgumentCaptor<LlmCallLog> captor = ArgumentCaptor.forClass(LlmCallLog.class);
        verify(callLogService, atLeastOnce()).record(captor.capture());
        return captor.getValue();
    }

    // ------------------------------------------------------------------ 正常路径

    @Test
    @DisplayName("正常:LLM 返回在枚举内 → 直接采用,不降级,response_model 有值")
    void normalClassify() {
        clientReturns("REFUND", "P1");
        clock.advance(Duration.ofMillis(0));

        ClassifyOutcome out = service.classify(TITLE, CONTENT);

        assertThat(out.category()).isEqualTo(TicketCategory.REFUND);
        assertThat(out.priority()).isEqualTo(TicketPriority.P1);
        assertThat(out.degraded()).isFalse();
        assertThat(out.degradeReason()).isNull();
        assertThat(out.responseModel()).isEqualTo("mock-classifier-v1");
        assertThat(out.contractViolated()).isFalse();
        assertThat(out.callLogId()).isEqualTo(1L);

        LlmCallLog log = lastLog();
        assertThat(log.getDegraded()).isFalse();
        assertThat(log.getScene()).isEqualTo(LlmScene.CLASSIFY);
        assertThat(log.getResponseModel()).isEqualTo("mock-classifier-v1");
        assertThat(log.getFinalCategory()).isEqualTo(TicketCategory.REFUND);
        assertThat(counter("llm.fallback")).isZero();
        assertThat(service.breaker().consecutiveFailures()).isZero();
    }

    @Test
    @DisplayName("宽松解析:分类大小写 / 首尾空白不算越界")
    void lenientEnumParsing() {
        clientReturns("  refund ", "p0");
        ClassifyOutcome out = service.classify(TITLE, CONTENT);
        assertThat(out.category()).isEqualTo(TicketCategory.REFUND);
        assertThat(out.priority()).isEqualTo(TicketPriority.P0);
        assertThat(out.contractViolated()).isFalse();
        assertThat(counter("llm.contract.violation")).isZero();
    }

    // ------------------------------------------------------------------ 契约越界

    @Test
    @DisplayName("分类越界(SPAM)→ 落 OTHER,contract_violation{field=category}+1,但这不算降级")
    void categoryOutOfEnumFallsToOther() {
        clientReturns("SPAM", "P1");

        ClassifyOutcome out = service.classify(TITLE, CONTENT);

        assertThat(out.category()).isEqualTo(TicketCategory.OTHER);
        assertThat(out.priority()).isEqualTo(TicketPriority.P1);
        assertThat(out.degraded()).as("越界不是降级:LLM 回答了,只是答错了").isFalse();
        assertThat(out.contractViolated()).isTrue();
        assertThat(out.rawCategory()).isEqualTo("SPAM");
        assertThat(counter("llm.contract.violation", "scene", "CLASSIFY", "field", "category")).isEqualTo(1);
        assertThat(counter("llm.fallback")).isZero();

        LlmCallLog log = lastLog();
        assertThat(log.getRawCategory()).isEqualTo("SPAM");
        assertThat(log.getFinalCategory()).isEqualTo(TicketCategory.OTHER);
        assertThat(log.getContractViolated()).isTrue();
        assertThat(log.getDegraded()).isFalse();
    }

    @Test
    @DisplayName("优先级越界(P9)→ 分类采用 LLM 的,优先级由规则按分类兜底")
    void priorityOutOfEnumUsesRules() {
        clientReturns("BILLING", "P9");

        ClassifyOutcome out = service.classify("账单问题", "紧急");

        assertThat(out.category()).isEqualTo(TicketCategory.BILLING);
        assertThat(out.priority()).as("规则:命中 P0 词 → P0").isEqualTo(TicketPriority.P0);
        assertThat(out.contractViolated()).isTrue();
        assertThat(counter("llm.contract.violation", "scene", "CLASSIFY", "field", "priority")).isEqualTo(1);
        assertThat(counter("llm.contract.violation", "scene", "CLASSIFY", "field", "category")).isZero();
    }

    @Test
    @DisplayName("分类为 null(响应缺字段)→ 同越界处理,落 OTHER")
    void nullCategoryTreatedAsViolation() {
        clientReturns(null, null);
        ClassifyOutcome out = service.classify("咨询", "x");
        assertThat(out.category()).isEqualTo(TicketCategory.OTHER);
        assertThat(out.priority()).isEqualTo(TicketPriority.P2);
        assertThat(out.contractViolated()).isTrue();
    }

    // ------------------------------------------------------------------ 降级

    @Test
    @DisplayName("超时 → 降级 TIMEOUT,走规则(REFUND/P1),耗时被如实记录,fallback{reason=TIMEOUT}+1")
    void timeoutFallsBackToRules() {
        clientFailsWith(DegradeReason.TIMEOUT, 3000);

        ClassifyOutcome out = service.classify(TITLE, CONTENT);

        assertThat(out.degraded()).isTrue();
        assertThat(out.degradeReason()).isEqualTo(DegradeReason.TIMEOUT);
        assertThat(out.category()).isEqualTo(TicketCategory.REFUND);
        assertThat(out.priority()).isEqualTo(TicketPriority.P1);
        assertThat(out.responseModel()).isNull();
        assertThat(out.latencyMs()).isEqualTo(3000);
        assertThat(counter("llm.fallback", "scene", "CLASSIFY", "reason", "TIMEOUT")).isEqualTo(1);
        assertThat(service.breaker().consecutiveFailures()).isEqualTo(1);

        LlmCallLog log = lastLog();
        assertThat(log.getDegraded()).isTrue();
        assertThat(log.getDegradeReason()).isEqualTo(DegradeReason.TIMEOUT);
        assertThat(log.getResponseModel()).isNull();
        assertThat(log.getLatencyMs()).isEqualTo(3000);
        assertThat(log.getFinalCategory()).isEqualTo(TicketCategory.REFUND);
    }

    @ParameterizedTest(name = "[{index}] 客户端失败原因 {0} → 降级原因原样透传")
    @EnumSource(value = DegradeReason.class, names = {"TIMEOUT", "UPSTREAM_ERROR", "BAD_RESPONSE"})
    @DisplayName("三种客户端失败都走规则,降级原因原样落盘")
    void everyClientFailureReasonIsRecorded(DegradeReason reason) {
        clientFailsWith(reason, 10);
        ClassifyOutcome out = service.classify("登录报错", "崩溃");
        assertThat(out.degraded()).isTrue();
        assertThat(out.degradeReason()).isEqualTo(reason);
        assertThat(out.category()).isEqualTo(TicketCategory.TECH);
        assertThat(out.priority()).isEqualTo(TicketPriority.P0);
        assertThat(counter("llm.fallback", "scene", "CLASSIFY", "reason", reason.name())).isEqualTo(1);
    }

    @Test
    @DisplayName("降级结果永远在枚举内、永远有值(ClassifyOutcome 的契约)")
    void fallbackAlwaysWithinContract() {
        clientFailsWith(DegradeReason.UPSTREAM_ERROR, 1);
        ClassifyOutcome out = service.classify("随便什么", "都不命中关键词");
        assertThat(out.category()).isNotNull().isIn((Object[]) TicketCategory.values());
        assertThat(out.priority()).isNotNull().isIn((Object[]) TicketPriority.values());
    }

    // ------------------------------------------------------------------ 熔断

    @Nested
    @DisplayName("熔断:连续失败 5 次 → 打开 60 秒 → 期间不发请求 → 到期自动恢复")
    class Circuit {

        @Test
        @DisplayName("第 5 次失败打开熔断,circuit_open_total+1;第 6 次调用不碰客户端,reason=CIRCUIT_OPEN")
        void fiveFailuresOpenTheCircuitAndShortCircuitTheSixthCall() {
            clientFailsWith(DegradeReason.UPSTREAM_ERROR, 5);

            for (int i = 1; i <= 4; i++) {
                service.classify(TITLE, CONTENT);
                assertThat(service.breaker().isOpen()).as("第 %d 次失败后仍闭合", i).isFalse();
            }
            assertThat(counter("llm.circuit.open")).isZero();

            service.classify(TITLE, CONTENT);
            assertThat(service.breaker().isOpen()).isTrue();
            assertThat(counter("llm.circuit.open", "scene", "CLASSIFY")).isEqualTo(1);

            ClassifyOutcome sixth = service.classify(TITLE, CONTENT);
            assertThat(sixth.degraded()).isTrue();
            assertThat(sixth.degradeReason()).isEqualTo(DegradeReason.CIRCUIT_OPEN);
            assertThat(sixth.latencyMs()).as("没发请求,耗时为 0").isZero();
            assertThat(sixth.category()).isEqualTo(TicketCategory.REFUND);
            verify(client, times(5)).classify(anyString(), anyString());
            assertThat(counter("llm.fallback", "scene", "CLASSIFY", "reason", "CIRCUIT_OPEN")).isEqualTo(1);
            assertThat(counter("llm.fallback", "scene", "CLASSIFY", "reason", "UPSTREAM_ERROR")).isEqualTo(5);

            LlmCallLog log = lastLog();
            assertThat(log.getDegradeReason()).isEqualTo(DegradeReason.CIRCUIT_OPEN);
            assertThat(log.getLatencyMs()).isZero();
        }

        @Test
        @DisplayName("60 秒后自动恢复:客户端重新被调用,成功后熔断保持闭合")
        void recoversAfterOpenWindow() {
            clientFailsWith(DegradeReason.TIMEOUT, 1);
            for (int i = 0; i < 5; i++) {
                service.classify(TITLE, CONTENT);
            }
            assertThat(service.breaker().isOpen()).isTrue();

            clock.advance(Duration.ofSeconds(59));
            service.classify(TITLE, CONTENT);
            verify(client, times(5)).classify(anyString(), anyString());   // 59 秒时仍未放行

            clock.advance(Duration.ofSeconds(1));
            clientReturns("REFUND", "P1");
            ClassifyOutcome out = service.classify(TITLE, CONTENT);
            verify(client, times(6)).classify(anyString(), anyString());   // 60 秒整放行
            assertThat(out.degraded()).isFalse();
            assertThat(service.breaker().isOpen()).isFalse();
            assertThat(service.breaker().consecutiveFailures()).isZero();
        }

        @Test
        @DisplayName("熔断器两个场景共用:分类失败 5 次,回复草稿也被短路")
        void breakerIsSharedAcrossScenes() {
            clientFailsWith(DegradeReason.UPSTREAM_ERROR, 1);
            for (int i = 0; i < 5; i++) {
                service.classify(TITLE, CONTENT);
            }
            DraftOutcome draft = service.draftReply(1L, TITLE, CONTENT, TicketCategory.REFUND);
            assertThat(draft.degraded()).isTrue();
            assertThat(draft.degradeReason()).isEqualTo(DegradeReason.CIRCUIT_OPEN);
            verify(client, never()).draftReply(anyString(), anyString(), anyString());
            assertThat(counter("llm.fallback", "scene", "DRAFT_REPLY", "reason", "CIRCUIT_OPEN")).isEqualTo(1);
        }

        @Test
        @DisplayName("中间一次成功打断连续计数:4 失败 + 成功 + 4 失败 不熔断")
        void successBreaksTheStreak() {
            clientFailsWith(DegradeReason.UPSTREAM_ERROR, 1);
            for (int i = 0; i < 4; i++) {
                service.classify(TITLE, CONTENT);
            }
            clientReturns("REFUND", "P1");
            service.classify(TITLE, CONTENT);
            clientFailsWith(DegradeReason.UPSTREAM_ERROR, 1);
            for (int i = 0; i < 4; i++) {
                service.classify(TITLE, CONTENT);
            }
            assertThat(service.breaker().isOpen()).isFalse();
            assertThat(counter("llm.circuit.open")).isZero();
        }

        @Test
        @DisplayName("契约越界不计入连续失败:5 次 SPAM 不会熔断")
        void contractViolationDoesNotCountAsFailure() {
            clientReturns("SPAM", "P1");
            for (int i = 0; i < 5; i++) {
                service.classify(TITLE, CONTENT);
            }
            assertThat(service.breaker().isOpen()).isFalse();
            assertThat(counter("llm.contract.violation", "scene", "CLASSIFY", "field", "category")).isEqualTo(5);
        }
    }

    // ------------------------------------------------------------------ 回复草稿

    @Nested
    @DisplayName("回复草稿(第二个调用点)")
    class Draft {

        @Test
        @DisplayName("正常:采用模型草稿,response_model 有值,ticket_id 落盘")
        void normalDraft() {
            when(client.draftReply(anyString(), anyString(), anyString()))
                    .thenReturn(new DraftResult("您好,已收到", "mock-writer-v1"));

            DraftOutcome out = service.draftReply(42L, TITLE, CONTENT, TicketCategory.REFUND);

            assertThat(out.draft()).isEqualTo("您好,已收到");
            assertThat(out.degraded()).isFalse();
            assertThat(out.responseModel()).isEqualTo("mock-writer-v1");
            LlmCallLog log = lastLog();
            assertThat(log.getScene()).isEqualTo(LlmScene.DRAFT_REPLY);
            assertThat(log.getTicketId()).isEqualTo(42L);
            assertThat(log.getDegraded()).isFalse();
        }

        @Test
        @DisplayName("超时 → 模板草稿,模板里带标题和分类,degraded=true reason=TIMEOUT")
        void timeoutFallsBackToTemplate() {
            when(client.draftReply(anyString(), anyString(), anyString())).thenAnswer(inv -> {
                throw failing(DegradeReason.TIMEOUT, 3000);
            });

            DraftOutcome out = service.draftReply(42L, TITLE, CONTENT, TicketCategory.REFUND);

            assertThat(out.degraded()).isTrue();
            assertThat(out.degradeReason()).isEqualTo(DegradeReason.TIMEOUT);
            assertThat(out.draft()).contains(TITLE).contains("REFUND");
            assertThat(out.responseModel()).isNull();
            assertThat(out.latencyMs()).isEqualTo(3000);
            assertThat(counter("llm.fallback", "scene", "DRAFT_REPLY", "reason", "TIMEOUT")).isEqualTo(1);
            assertThat(service.breaker().consecutiveFailures()).isEqualTo(1);
        }

        @Test
        @DisplayName("响应缺 draft 字段(BAD_RESPONSE)→ 模板,且计入熔断计数")
        void badResponseCountsTowardsCircuit() {
            when(client.draftReply(anyString(), anyString(), anyString()))
                    .thenThrow(new LlmException(DegradeReason.BAD_RESPONSE, "缺 draft"));
            DraftOutcome out = service.draftReply(42L, TITLE, CONTENT, TicketCategory.OTHER);
            assertThat(out.degradeReason()).isEqualTo(DegradeReason.BAD_RESPONSE);
            assertThat(service.breaker().consecutiveFailures()).isEqualTo(1);
        }
    }
}
