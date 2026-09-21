package com.ticketqa.llm;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketqa.config.LlmProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.net.http.HttpClient;
import java.time.Duration;

/**
 * 按 llm.mode 装配 LlmClient 的其中一个实现。
 * @ConditionalOnProperty 在容器刷新阶段求值:两个 @Bean 方法只有一个会被注册,
 * 所以 LlmService 注入 LlmClient 时不会有"找到两个候选"的歧义。
 *
 * 超时落在 HTTP 客户端上(JDK HttpClient 的请求级 timeout),不是另起线程池 + Future.get(timeout):
 * 少一个线程池、没有线程泄漏、超时时连接会被真正取消(ADR-004)。
 */
@Configuration
public class LlmClientConfig {

    private static final Logger log = LoggerFactory.getLogger(LlmClientConfig.class);

    @Bean
    @ConditionalOnProperty(name = "llm.mode", havingValue = "real")
    public LlmClient realLlmClient(LlmProperties props, ObjectMapper objectMapper) {
        if (props.real().apiKey() == null || props.real().apiKey().isBlank()) {
            log.warn("llm.mode=real 但 LLM_API_KEY 为空,真实调用会得到 401 并走降级");
        }
        RestClient client = RestClient.builder()
                .baseUrl(props.real().baseUrl())
                .requestFactory(requestFactory(props.timeoutMs()))
                .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + props.real().apiKey())
                .build();
        log.info("LlmClient = 真实调用 baseUrl={} model={} timeout={}ms", props.real().baseUrl(), props.real().model(), props.timeoutMs());
        return new OpenAiCompatibleLlmClient(client, objectMapper, props.real().model());
    }

    @Bean
    @ConditionalOnProperty(name = "llm.mode", havingValue = "mock", matchIfMissing = true)
    public LlmClient wireMockLlmClient(LlmProperties props, ObjectMapper objectMapper) {
        RestClient client = RestClient.builder()
                .baseUrl(props.mock().baseUrl())
                .requestFactory(requestFactory(props.timeoutMs()))
                .build();
        log.info("LlmClient = WireMock 挡板 baseUrl={} timeout={}ms", props.mock().baseUrl(), props.timeoutMs());
        return new WireMockLlmClient(client, objectMapper, props.mock().model());
    }

    /**
     * 强制 HTTP/1.1:JDK HttpClient 默认先尝试 h2c 升级(Connection: Upgrade, HTTP2-Settings),
     * WireMock 的 Jetty 会接受升级,随后请求体丢失、流被 RST_STREAM 取消——联调时所有调用都被
     * 判成 UPSTREAM_ERROR 走了规则,靠 llm_call_log 里 degraded=1 才发现。真实供应商走 HTTPS 也不需要 h2c。
     */
    private static JdkClientHttpRequestFactory requestFactory(long timeoutMs) {
        HttpClient httpClient = HttpClient.newBuilder()
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofMillis(Math.min(timeoutMs, 2000)))
                .build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(httpClient);
        factory.setReadTimeout(Duration.ofMillis(timeoutMs));
        return factory;
    }
}
