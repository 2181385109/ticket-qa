"""
自研接口自动化封装(ADR-012)。

四层:
  config    环境(local / ci)→ 一组地址和口令
  client    ApiClient:统一鉴权头、请求日志、Allure 附件、耗时
  response  ApiResponse + Expect:响应断言 DSL,不只断状态码
  factory   TicketFactory:造数 + 用例级清理(直连 MySQL 硬删)
外加三个"旁路观测"工具:db(MySQL)、wiremock(挡板收到了什么)、metrics(Prometheus 指标)、mq(重投消息)。

设计原则只有一条:接口层面看不出的事,用旁路证据断言。
LLM 路径的 degraded / response_model 只有 llm_call_log 表和指标能证明(docs/findings/20260920 的教训)。
"""
