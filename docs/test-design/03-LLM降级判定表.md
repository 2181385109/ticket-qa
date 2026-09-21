# 03 · LLM 降级判定表

方法:**判定表法**(主)+ **等价类划分**(客户端失败原因、规则分类器输入)+ **场景法**(熔断生命周期)。

为什么用判定表:LLM 路径的行为由几个条件共同决定——熔断器开没开、客户端成功没有、返回值在不在枚举内——
每个条件两三个取值,组合出的动作又不止一个(走规则 / 采用 / 落 OTHER / 打哪个指标 / 落盘记录长什么样)。
这种"多条件 → 多动作"的逻辑,判定表能保证每个组合都被点到,而且表本身就是和开发对规格的载体。

## 1. 分类调用点(CLASSIFY)的判定表

条件:
- C1 熔断器打开?
- C2 客户端结果:成功 / TIMEOUT / UPSTREAM_ERROR / BAD_RESPONSE
- C3 返回的 category 在枚举内?
- C4 返回的 priority 在枚举内?

动作:
- A1 分类来源:LLM / 规则 / OTHER
- A2 优先级来源:LLM / 规则
- A3 `degraded` / `degrade_reason`
- A4 `response_model` 有值?
- A5 指标:`llm_fallback_total{reason}` / `llm_contract_violation_total{field}` / `llm_circuit_open_total`
- A6 计入熔断连续失败?
- A7 落盘 `raw_category` / `contract_violated`

| # | C1 熔断 | C2 客户端 | C3 cat 合法 | C4 pri 合法 | A1 分类 | A2 优先级 | A3 degraded/reason | A4 model | A5 指标 | A6 计失败 | A7 raw/violated | 用例 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | 否 | 成功 | 是 | 是 | LLM | LLM | false / — | 有 | 无 | 否(计数清零) | raw=cat / 0 | 单测 `normalClassify`;接口 `test_keyword_routes`(4 类) |
| R2 | 否 | 成功 | 是(大小写/空白) | 是 | LLM | LLM | false | 有 | 无 | 否 | 0 | `lenientEnumParsing` |
| R3 | 否 | 成功 | **否**(SPAM) | 是 | **OTHER** | LLM | false | 有 | contract{field=category}+1 | **否** | raw=SPAM / 1 | 单测 `categoryOutOfEnumFallsToOther`;接口 `test_out_of_enum_category` |
| R4 | 否 | 成功 | 是 | **否**(P9) | LLM | **规则** | false | 有 | contract{field=priority}+1 | 否 | 1 | 单测 `priorityOutOfEnumUsesRules`;接口 `test_out_of_enum_priority_via_temp_stub`(临时桩) |
| R5 | 否 | 成功 | null | null | OTHER | 规则 | false | 有 | contract ×2 | 否 | 1 | `nullCategoryTreatedAsViolation` |
| R6 | 否 | TIMEOUT | — | — | 规则 | 规则 | true / TIMEOUT | 空 | fallback{TIMEOUT}+1 | 是 | null / 0 | 单测 `timeoutFallsBackToRules`;接口 `test_timeout_falls_back_to_rules`(≥3000ms,挡板收到 1 个请求) |
| R7 | 否 | UPSTREAM_ERROR | — | — | 规则 | 规则 | true / UPSTREAM_ERROR | 空 | fallback{UPSTREAM_ERROR}+1 | 是 | null / 0 | 单测 `everyClientFailureReasonIsRecorded`;接口 `test_upstream_error_falls_back` |
| R8 | 否 | BAD_RESPONSE | — | — | 规则 | 规则 | true / BAD_RESPONSE | 空 | fallback{BAD_RESPONSE}+1 | 是 | null / 0 | 同上;接口 `test_bad_json_falls_back` |
| R9 | **是** | (不调用) | — | — | 规则 | 规则 | true / CIRCUIT_OPEN | 空 | fallback{CIRCUIT_OPEN}+1,latency=0 | — | null / 0 | 单测 `fiveFailuresOpenTheCircuitAndShortCircuitTheSixthCall`;接口 `test_open_circuit_short_circuits_everything`(挡板收到 0 个请求) |

R3 是这张表里最容易被误解的一行:**越界不是降级**。LLM 回答了,只是答错了;`degraded=false`、`response_model` 有值,
但 `contract_violated=1`、`raw_category` 保留原始值。它不计入熔断——5 次 SPAM 不会打开熔断器(`contractViolationDoesNotCountAsFailure`)。

不可能的组合(C1=是 时 C2~C4 无意义)已经合并进 R9。

### 固定断言项(来自 docs/findings/20260920)

R1 的接口用例必须同时断:响应 category 正确 **且** `llm_call_log.degraded=0` **且** `response_model='mock-classifier-v1'`
**且** 挡板收到了带该标题的请求。缺了后三条,h2c 那类"全部静默降级"的故障会让用例继续绿——
因为规则和挡板用同一套关键词,降级路径给出的答案和正常路径一模一样。

## 2. 回复草稿调用点(DRAFT_REPLY)

条件比分类少一个(草稿没有"越界",缺字段就是坏响应):

| # | 熔断 | 客户端 | 动作 | 用例 |
|---|---|---|---|---|
| D1 | 否 | 成功 | 采用草稿,degraded=false,response_model=mock-writer-v1,落盘 ticket_id | 单测 `normalDraft`;接口 `test_normal_draft`(草稿含标题与分类) |
| D2 | 否 | TIMEOUT | 模板草稿(含标题、分类),reason=TIMEOUT,latency≥3000,计失败 | 单测 `timeoutFallsBackToTemplate`;接口 `test_timeout_draft_uses_template` |
| D3 | 否 | 缺 draft 字段 → BAD_RESPONSE | 模板,计失败 | 单测 `badResponseCountsTowardsCircuit`;客户端层 `draftMissingFieldIsBadResponse` / `draftNullIsBadResponse` |
| D4 | 否 | 500 → UPSTREAM_ERROR | 模板 | 接口 `test_upstream_error_draft` |
| D5 | 是 | 不调用 | 模板,reason=CIRCUIT_OPEN,latency=0 | 单测 `breakerIsSharedAcrossScenes`;接口 `test_open_circuit_short_circuits_everything` |

D5 同时证明**两个调用点共用一个熔断器**:分类失败 5 次,草稿也被短路。

## 3. 熔断器生命周期——场景法 + 边界值

阈值(ADR-004):连续失败 5 次,打开 60 秒。两个维度各取边界:

| 维度 | 点 | 期望 | 用例 |
|---|---|---|---|
| 失败次数 | 4 | 闭合 | `CircuitBreakerTest.fourFailuresStayClosed`;接口 `test_five_failures_open_the_circuit` 前 4 次断 state=0 |
| 失败次数 | **5** | **打开**,`recordFailure` 返回 true,`llm_circuit_open_total`+1 | `fifthFailureTrips`;接口同上第 5 次 |
| 连续性 | 4 失败 + 1 成功 + 4 失败 | 闭合(成功清零) | `successResetsConsecutiveCount`、`successBreaksTheStreak`;接口 `test_no_half_open_state` |
| 打开时长 | 59.999s | 仍打开 | `closesExactlyAfterOpenWindow`(拨表);`recoversAfterOpenWindow` 59s 不放行 |
| 打开时长 | **60s 整** | **闭合**(`now < openUntil` 不成立) | 同上;接口 `test_recovers_after_open_window`(真等 ≤65s,断 state 回 0、挡板重新收到请求) |
| 恢复后 | 再 4 次失败 | 仍闭合(没有半开,计数从 0 累) | `reopensOnlyAfterAnotherFullRun`;接口 `test_no_half_open_state` |
| 退化 | 阈值 1 | 第一次失败即打开 | `thresholdOneTripsImmediately` |

接口层的熔断用例打 `circuit` 标记、排在会话最后,模块前后都等 `llm_circuit_state` 回 0(ADR-012)。
其他 LLM 用例每条降级用例结束做一次成功调用清零计数(`reset_streak` fixture),防止跨用例累计到 5。

## 4. 客户端层——等价类(`WireMockLlmClientTest`,MockRestServiceServer)

| 响应 | 等价类 | 期望 | 用例 |
|---|---|---|---|
| 2xx 字段齐全 | 有效 | 原样返回 raw(含越界值,客户端不做主) | `classifyHappyPath` |
| 2xx 缺字段 | 有效(缺失 → null) | raw 为 null,由上层按越界处理 | `classifyMissingFieldsBecomeNull` |
| 2xx 非 JSON | 无效 | BAD_RESPONSE | `nonJsonBodyIsBadResponse` |
| 500 / 429 | 无效 | UPSTREAM_ERROR | `serverErrorIsUpstream`、`tooManyRequestsIsUpstream` |
| draft 缺 / null | 无效 | BAD_RESPONSE | `draftMissingFieldIsBadResponse`、`draftNullIsBadResponse` |

异常翻译(`LlmHttpSupportTest`)按异常类型分等价类:三种超时异常(含 Spring 包在 IOException 里的 `TimeoutException`——联调时的教训)→ TIMEOUT;
其他 I/O、HTTP 4xx/5xx → UPSTREAM_ERROR;LlmException 透传;其余 → BAD_RESPONSE。

## 5. 规则分类器——等价类(降级路径的确定性保证)

输入按命中的关键词类划分:REFUND / BILLING / TECH / 无命中(OTHER),加"同时命中多类"(表顺序决定,REFUND 先)和"空 / null"。
优先级:命中 P0 词 → P0;否则 OTHER → P2、其余 → P1。用例 `KeywordRuleClassifierTest`(9 组参数化 + null + 确定性)。

注意:`[ERROR]` 这个挡板故障标记本身含 `error`,会被规则算成 TECH(known-issues KI-006 的相邻观察);
设计降级用例的标题时要把这一点算进期望值。
