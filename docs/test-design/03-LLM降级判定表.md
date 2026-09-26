# 03 · LLM 降级判定表

方法:**判定表法**(主)+ **等价类划分**(客户端失败原因、规则分类器输入)+ **场景法**(熔断生命周期)。

为什么用判定表:LLM 路径的行为由几个条件共同决定——熔断器开没开、客户端成功没有、返回值在不在枚举内——
每个条件两三个取值,组合出的动作又不止一个(走规则 / 采用 / 落 OTHER / 打哪个指标 / 落盘记录长什么样)。
这种"多条件 → 多动作"的逻辑,判定表能保证每个组合都被点到,而且表本身就是和开发对规格的载体。

## 1. 分类调用点(CLASSIFY)的判定表

条件:
- C1 熔断器打开?
- C2 客户端结果:成功 / TIMEOUT / UPSTREAM_ERROR / BAD_RESPONSE / MIXED_OUTPUT(第二阶段,见 §1.2)
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

### 1.1 第二阶段:交叉校验与严格解析(ADR-024,2026-09-25 加)

R1 在第二阶段被拆开:C3、C4 都合法之后,多一个条件 **C5 与关键词规则是否冲突**(阈值开跑前冻结,见 ADR-024"交叉校验阈值")。
另加动作 A8 `needs_review / review_reason`、A9 `rule_category / rule_priority`(每次分类都落,包括降级)。

| # | C5 规则命中集合 / 规则优先级 | 模型输出 | A1 分类 | A2 优先级 | A8 复核 | A5 指标 | A6 计失败 | 用例 |
|---|---|---|---|---|---|---|---|---|
| R10 | 命中 ∅ / **P2** | 任意 / **P0** | **规则** | **规则** | 1 / PRIORITY_CONFLICT | review{PRIORITY_CONFLICT}+1 | 否 | 单测 `priorityConflictAdoptsRule`、`ClassifyCrossCheckTest.priorityGrid`(3×3 全组合);接口 `test_obeyed_p0_is_flagged_for_review` |
| R11 | 命中 {REFUND} | **TECH** / 任意 | **规则** | **规则**(两个维度一起换) | 1 / CATEGORY_CONFLICT | review{CATEGORY_CONFLICT}+1 | 否 | 单测 `categoryConflictAdoptsRuleForBothFields`、`categoryTable`;接口 `test_obeyed_category_is_flagged_for_review` |
| R12 | 命中 {REFUND, BILLING} | BILLING / P1 | LLM | LLM | 0 | 无 | 否 | 单测 `noConflictStillRecordsRule`(规则结论照样落盘) |
| R13 | 命中 ∅ / **P0**(注入里夹带"紧急") | OTHER / P0 | LLM | LLM(P0) | 0 | 无 | 否 | **已知绕过**:单测 `keywordStuffingBypassesPriorityCheck`;接口 `test_known_bypass_keyword_stuffing` |
| R14 | — | 越界字段(R3 / R4) | 按 R3 / R4 | 按 R3 / R4 | 越界字段不参与比对 | 按 R3 / R4 | 否 | 单测 `violatedCategoryIsNotCrossChecked`、`violatedFieldsAreSkipped` |

### 1.2 第二阶段:严格解析拆成两个原因(ADR-024"严格解析与熔断",2026-09-26 v1 复测前定稿)

修复 KI-022 之后,content 必须**恰好是一个 JSON 对象**。不合格的输出按"文本里某处读不读得出一个完整 JSON 对象"再分两类——
C2 由原来的一个取值 BAD_RESPONSE 拆成两个,A6(计入熔断)的取值相反:

| # | C1 熔断 | C2 客户端(content 形态) | A1 分类 | A2 优先级 | A3 degraded/reason | A4 model | A5 指标 | A6 计失败 | A7 raw/violated | 用例 |
|---|---|---|---|---|---|---|---|---|---|---|
| R8 | 否 | **读不出任何完整对象**(非 JSON、截断、只有 `{` 的自然语言、`[1,2]`)→ BAD_RESPONSE | 规则 | 规则 | true / BAD_RESPONSE | 空 | fallback{BAD_RESPONSE}+1 | **是** | null / 0 | 单测 `notJson` / `truncatedObject` / `braceWithoutObject` / `jsonArrayWithoutObject`、`MixedOutput.badResponseStillTripsBreaker`;接口 `test_bad_json_falls_back` |
| R8b | 否 | **读得出完整对象但不是恰好一个**(两个对象、对象后跟文字、提示词原文 + JSON、数组包对象)→ **MIXED_OUTPUT** | 规则 | 规则 | true / MIXED_OUTPUT | 空 | fallback{MIXED_OUTPUT}+1 | **否**(记成功,计数清零) | null / 0 | 单测 `trailingObjectIsRejected` / `promptTemplateEchoedFirstIsRejected` / `objectFollowedByProse` / `jsonArrayWrappingObject`、`WireMockLlmClientTest.trailingJsonIsMixedOutput`、`MixedOutput.*`;接口 `test_trailing_json_is_rejected`(`[TWO_JSON]`)、`test_mixed_output_does_not_open_circuit`(`[ECHO_PROMPT]` ×6) |

R8b 和 D6(UNSAFE_OUTPUT)是同一个理由:**攻击者能稳定诱导出来的输出,不能成为熔断开关**——第一阶段 D-004 让模型先复述提示词原文
(里面带 JSON 模板)、最后才给答案,正是 R8b 的形态;如果它计入熔断,5 张这样的工单就能让全站 LLM 分类熔断 60 秒。
R8 仍计入:"一个完整对象都读不出来"是模型整体格式崩坏的信号,正是熔断要保护的场景(ADR-004)。
两类的边界本身用边界值钉住:截断的对象(差一个 `}`)→ R8;数组 `[1,2]` → R8,数组里包着对象 → R8b。

接口用例 `test_mixed_output_does_not_open_circuit` 的 N 取 6(> 阈值 5):连续 6 次 R8b 后 `llm_circuit_open_total` 增量 0、
`llm_fallback_total{CIRCUIT_OPEN}` 增量 0,紧接着的正常建单 `degraded=0`。反向验证:把 `MIXED_OUTPUT` 改成计入熔断,
`LlmServiceTest$MixedOutput` 5 条里 3 条变红(2026-09-26 本地手动变异)。

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

第二阶段(ADR-024)在 D1 后面加一个条件 **输出检查是否命中**:

| # | 熔断 | 客户端 | 输出检查 | 动作 | 用例 |
|---|---|---|---|---|---|
| D6 | 否 | 成功 | 命中承诺词 | 模板草稿,reason=**UNSAFE_OUTPUT**,response_model **有值**,review_reason=UNSAFE_PROMISE,**不计失败** | 单测 `promiseIsReplacedByTemplate`;接口 `test_promise_draft_is_blocked` |
| D7 | 否 | 成功 | 命中提示词 8 字片段 | 同上,review_reason 含 UNSAFE_LEAK | 单测 `leakIsReplacedByTemplate`;接口 `test_leak_draft_is_blocked` |
| D8 | 否 | 成功 ×10 | 每次都命中 | 熔断器不打开,连续失败计数 0 | 单测 `unsafeOutputDoesNotTripBreaker`;接口 `test_unsafe_drafts_do_not_open_circuit` |

D6 与 D2 的区别是 A6:UNSAFE_OUTPUT 是防御动作不是故障——计入熔断的话,攻击者提交 5 张注入工单各取一次草稿就能让全站 LLM 熔断 60 秒。
检查本身的等价类(词表内 / 全角 / 插空格 / 否定句照拦 / 换说法漏过;逐字 / 换标点复述 / 7 字放行 8 字拦截 / 完全转述漏过)在 `DraftOutputPolicyTest`。

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
| 2xx 两个 JSON 对象 | 无效(夹带) | MIXED_OUTPUT(§1.2 R8b) | `trailingJsonIsMixedOutput` |
| 500 / 429 | 无效 | UPSTREAM_ERROR | `serverErrorIsUpstream`、`tooManyRequestsIsUpstream` |
| draft 缺 / null | 无效 | BAD_RESPONSE | `draftMissingFieldIsBadResponse`、`draftNullIsBadResponse` |

异常翻译(`LlmHttpSupportTest`)按异常类型分等价类:三种超时异常(含 Spring 包在 IOException 里的 `TimeoutException`——联调时的教训)→ TIMEOUT;
其他 I/O、HTTP 4xx/5xx → UPSTREAM_ERROR;LlmException 透传(`LlmJson` 抛的 MIXED_OUTPUT / BAD_RESPONSE 走这一条);其余 → BAD_RESPONSE。

## 5. 规则分类器——等价类(降级路径的确定性保证)

输入按命中的关键词类划分:REFUND / BILLING / TECH / 无命中(OTHER),加"同时命中多类"(表顺序决定,REFUND 先)和"空 / null"。
优先级:命中 P0 词 → P0;否则 OTHER → P2、其余 → P1。用例 `KeywordRuleClassifierTest`(9 组参数化 + null + 确定性)。

注意:`[ERROR]` 这个挡板故障标记本身含 `error`,会被规则算成 TECH(known-issues KI-006 的相邻观察);
设计降级用例的标题时要把这一点算进期望值。
