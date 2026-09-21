package com.ticketqa.llm;

import com.ticketqa.domain.enums.DegradeReason;
import com.ticketqa.domain.enums.LlmScene;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * KI-007 / KI-015:带标签的 Counter 在第一次发生前必须已经以 0 存在,面板才能从 0 开始而不是 "No data"。
 * 断言的是"构造后立刻能在 registry 里找到全部 scene × reason 组合",以及预注册和真实打点共用同一个 Counter(register 幂等)。
 */
class LlmMetricsTest {

    @Test
    @DisplayName("构造后 llm.fallback 的 2 场景 × 4 原因、llm.circuit.open 的 2 场景、llm.contract.violation 的 2 场景 × 2 字段全部存在且为 0")
    void allLabelCombinationsPreRegisteredAtZero() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        new LlmMetrics(registry);

        for (LlmScene scene : LlmScene.values()) {
            for (DegradeReason reason : DegradeReason.values()) {
                Counter c = registry.find("llm.fallback").tag("scene", scene.name()).tag("reason", reason.name()).counter();
                assertThat(c).as("llm.fallback{scene=%s,reason=%s}", scene, reason).isNotNull();
                assertThat(c.count()).isZero();
            }
            assertThat(registry.find("llm.circuit.open").tag("scene", scene.name()).counter()).isNotNull();
            for (String field : new String[]{"category", "priority"}) {
                assertThat(registry.find("llm.contract.violation").tag("scene", scene.name()).tag("field", field).counter())
                        .as("llm.contract.violation{scene=%s,field=%s}", scene, field).isNotNull();
            }
        }
        assertThat(registry.find("llm.fallback").counters()).hasSize(LlmScene.values().length * DegradeReason.values().length);
    }

    @Test
    @DisplayName("打点落在预注册的那个 Counter 上(register 幂等),不会出现同标签的第二条序列")
    void incrementHitsPreRegisteredCounter() {
        SimpleMeterRegistry registry = new SimpleMeterRegistry();
        LlmMetrics metrics = new LlmMetrics(registry);

        metrics.fallback(LlmScene.CLASSIFY, DegradeReason.TIMEOUT);
        metrics.fallback(LlmScene.CLASSIFY, DegradeReason.TIMEOUT);
        metrics.circuitOpened(LlmScene.DRAFT_REPLY);

        assertThat(registry.find("llm.fallback").tag("scene", "CLASSIFY").tag("reason", "TIMEOUT").counter().count()).isEqualTo(2);
        assertThat(registry.find("llm.fallback").tag("scene", "CLASSIFY").tag("reason", "CIRCUIT_OPEN").counter().count()).isZero();
        assertThat(registry.find("llm.circuit.open").tag("scene", "DRAFT_REPLY").counter().count()).isEqualTo(1);
        assertThat(registry.find("llm.fallback").counters()).hasSize(8);
    }
}
