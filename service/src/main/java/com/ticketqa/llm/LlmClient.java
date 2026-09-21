package com.ticketqa.llm;

/**
 * LLM 调用的统一接口(CLAUDE.md §5.5)。两个实现:
 *   - OpenAiCompatibleLlmClient  真实调用(DeepSeek / OpenAI 兼容协议)
 *   - WireMockLlmClient          挡板,走 WireMock 容器
 * 由 llm.mode 决定装配哪一个(LlmClientConfig)。
 *
 * 实现只负责"发请求、拿原始结果",不做超时降级、熔断、契约校验——那些在 LlmService 里,
 * 这样两个实现共享同一套韧性逻辑,挡板测出来的降级路径和真实调用是同一段代码。
 *
 * 失败一律抛 LlmException 并带上 DegradeReason,由 LlmService 决定怎么降级。
 */
public interface LlmClient {

    /** 配置里请求的模型名,落到 llm_call_log.request_model */
    String requestModel();

    ClassifyResult classify(String title, String content);

    DraftResult draftReply(String title, String content, String category);
}
