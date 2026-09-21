package com.ticketqa.llm;

import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.LlmScene;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.function.Supplier;

/**
 * LLM 路径的指标(CLAUDE.md §5.5 点名了 llm_fallback_total 和 llm_circuit_open_total)。
 * Micrometer 的 Counter/Timer 按 tag 组合惰性创建;Prometheus 端点里名字会变成 llm_fallback_total{scene="CLASSIFY",reason="TIMEOUT"}。
 * 命名注意:Micrometer 里叫 "llm.fallback",导出到 Prometheus 时自动转成 llm_fallback_total(Counter 会加 _total 后缀)。
 *
 * 构造时把 scene × reason 的全部组合预注册成 0(KI-007 / KI-015):否则第一次降级发生前端点上没有这条序列,
 * Grafana 面板显示 "No data" 而不是 0,`increase()` 在第一个采样点也算不出来。
 * 预注册的只有 Counter;Timer(llm_call_duration_seconds)仍是惰性的——它按 outcome 打标签,outcome 集合是开放的。
 */
@Component
public class LlmMetrics {

    private final MeterRegistry registry;

    public LlmMetrics(MeterRegistry registry) {
        this.registry = registry;
        for (LlmScene scene : LlmScene.values()) {
            for (DegradeReason reason : DegradeReason.values()) {
                fallbackCounter(scene, reason);
            }
            circuitOpenCounter(scene);
            contractViolationCounter(scene, "category");
            contractViolationCounter(scene, "priority");
        }
    }

    public void fallback(LlmScene scene, DegradeReason reason) {
        fallbackCounter(scene, reason).increment();
    }

    public void circuitOpened(LlmScene scene) {
        circuitOpenCounter(scene).increment();
    }

    public void contractViolation(LlmScene scene, String field) {
        contractViolationCounter(scene, field).increment();
    }

    /** register 是幂等的:同名同 tag 返回同一个 Counter,所以预注册和使用共用这几个方法 */
    private Counter fallbackCounter(LlmScene scene, DegradeReason reason) {
        return Counter.builder("llm.fallback")
                .description("LLM 降级到规则的次数")
                .tag("scene", scene.name())
                .tag("reason", reason.name())
                .register(registry);
    }

    private Counter circuitOpenCounter(LlmScene scene) {
        return Counter.builder("llm.circuit.open")
                .description("熔断器被打开的次数")
                .tag("scene", scene.name())
                .register(registry);
    }

    private Counter contractViolationCounter(LlmScene scene, String field) {
        return Counter.builder("llm.contract.violation")
                .description("LLM 返回值越出枚举的次数")
                .tag("scene", scene.name())
                .tag("field", field)
                .register(registry);
    }

    public void callDuration(LlmScene scene, String outcome, Duration duration) {
        Timer.builder("llm.call.duration")
                .description("LLM 调用耗时(含超时的失败调用)")
                .tag("scene", scene.name())
                .tag("outcome", outcome)
                .publishPercentiles(0.5, 0.95, 0.99)
                .register(registry)
                .record(duration);
    }

    public void registerCircuitGauge(Supplier<Number> stateSupplier) {
        Gauge.builder("llm.circuit.state", stateSupplier)
                .description("熔断器状态 1=打开 0=闭合")
                .register(registry);
    }
}
