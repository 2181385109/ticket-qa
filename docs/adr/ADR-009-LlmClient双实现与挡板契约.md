# ADR-009: LlmClient 两个实现按配置装配,挡板用自己的简化契约而不是复刻 OpenAI 协议

## 背景

CLAUDE.md §5.5:所有 LLM 调用走统一 `LlmClient` 接口,两个实现——真实调用 + WireMock 挡板,
接口自动化默认走挡板。要决定:两个实现怎么切换、挡板说什么协议、韧性逻辑
(超时 / 熔断 / 契约校验 / 落盘)放在实现里还是实现外。

## 选项

### 韧性逻辑放哪

- **方案 A:每个实现自己做超时、熔断、降级**
  代价:两份逻辑,挡板测出来的降级路径和线上跑的不是同一段代码——测了等于没测。

- **方案 B:实现只负责"发请求、拿原始结果",韧性逻辑在外层 `LlmService`** ← 采用
  做法:`LlmClient` 接口只有 `classify()` / `draftReply()` / `requestModel()`,失败抛
  `LlmException(reason)`。`LlmService` 包一层:查熔断器 → 调实现 → 翻译异常 → 契约校验 →
  落盘 → 打点。挡板制造的 `[SLOW]`、`[ERROR]` 走的是和线上完全相同的降级代码。
  代价:多一个类;实现和外壳的职责边界要在注释里写清楚。

### 两个实现怎么切换

- **方案 A:Spring Profile(`@Profile("mock")`)**
  代价:Profile 是"环境"级别的开关,和 dev / test / prod 混在一起;想在 prod 配置下
  临时切挡板排查问题,得改 profile 列表。

- **方案 B:`@ConditionalOnProperty(name = "llm.mode", havingValue = ...)`** ← 采用
  做法:`llm.mode=real|mock`,环境变量 `LLM_MODE` 覆盖,默认 `mock`。
  两个 `@Bean` 方法互斥,容器里永远只有一个 `LlmClient`,注入时没有歧义。
  代价:是一个独立于 profile 的开关,多一个要记的配置项。

### 挡板说什么协议

- **方案 A:挡板复刻 OpenAI `/chat/completions` 协议,真实实现改个 base-url 就是挡板**
  做法:WireMock 桩返回 `{"choices":[{"message":{"content":"{\"category\":...}"}}]}`。
  代价:JSON 套 JSON 字符串,桩文件难读难改;桩要按 `messages[1].content` 做正则匹配,
  改 prompt 格式桩就失效;"两个实现"实际上是一个实现两个 URL,和规格字面不符。
  好处:真实实现的解析代码也被挡板覆盖到了。

- **方案 B:挡板有自己的简化契约,独立实现类** ← 采用
  做法:`WireMockLlmClient` 调 `POST /mock/llm/classify {"title","content"}` →
  `{"model","category","priority"}`;`POST /mock/llm/draft` → `{"model","draft"}`。
  桩按标题里的标记触发故障:`[SLOW]` 延迟 5 秒、`[ERROR]` 返 500、`[BAD_CATEGORY]`
  返 `SPAM`、`[BAD_JSON]` 返非 JSON;按关键词正则返回 REFUND / BILLING / TECH,兜底 OTHER。
  代价:`OpenAiCompatibleLlmClient` 的响应解析代码(`choices[0].message.content` 取值、
  二次 JSON 解析)没有被挡板覆盖,需要单测用 MockRestServiceServer 单独测。
  好处:桩是扁平 JSON,一眼能读;故障注入用标题标记,接口测试写起来就是改一个字符串;
  挡板的职责是"可控地制造行为",不是"模仿供应商"。

## 决定

- 韧性逻辑在 `LlmService`,两个实现只做 HTTP。
- `llm.mode` 开关,`@ConditionalOnProperty`,默认 `mock`。
- 挡板用简化契约,独立实现类,故障用标题标记触发。
- 真实实现走 OpenAI 兼容协议(`/chat/completions`,`response_format=json_object`,
  `temperature=0`),默认指向 DeepSeek,`LLM_API_KEY` 空时启动打 WARN 但不阻止启动
  (真实调用会得到 401 → `UPSTREAM_ERROR` → 走规则)。
- 两个实现共用的异常翻译在 `LlmHttpSupport`:`HttpTimeoutException` → TIMEOUT,
  `RestClientResponseException` → UPSTREAM_ERROR,其他 → BAD_RESPONSE。
- 落盘的"请求模型名"来自配置,"响应模型名"来自响应体的 `model` 字段——两者不一致
  是供应商在背后换模型的信号,这是把两个都记下来的理由。

## 后果

- 接受:真实实现的解析逻辑不被挡板覆盖。它是 30 行 JSON 取值,单测足够。
- 接受:挡板的分类规则是正则关键词,和线上模型的行为无关。接口测试断言的是**契约**
  (分类在枚举内、降级时 degraded=true)和**韧性路径**(超时降级、熔断打开),不是分类准确率。
  准确率是模型评测的事,不在这个测试体系里。
- 接受:挡板是独立容器,不是进程内 WireMock。单测(下一阶段)会用进程内 WireMock
  或 MockRestServiceServer,那时两种挡板并存。
- 什么场景下会是错的:需要在挡板上验证 prompt 变更是否破坏解析——那必须让挡板说真实协议。
  可以给 WireMock 再加一组 `/chat/completions` 的桩、把 `llm.real.base-url` 指过去,
  两种方式并存,不冲突。

## 常见质疑与回应

**Q:挡板为什么不直接模拟 OpenAI 协议?改个 URL 不就行了,还省一个类。**
> 省一个类,但桩会变成 JSON 里套 JSON 字符串——`content` 字段是一个转义过的 JSON 文本,
> 桩文件没法读、改 prompt 格式桩就失效。更根本的是挡板的职责:它是用来可控地制造
> "慢、错、越界"这些行为的,不是用来模仿供应商的。简化契约让故障注入变成标题里加个
> `[SLOW]`,接口测试写起来是改一个字符串。代价是真实实现的解析代码没被挡板覆盖,
> 我用单测补,30 行代码。

**Q:那你的"两个实现"是不是为了凑规格?**
> 不是。两个实现说的是两种协议——供应商协议和测试协议——而不是两个 URL。它们共享同一层
> 韧性逻辑,这才是关键:挡板触发的超时、熔断,走的是和线上一模一样的 `LlmService` 代码。
> 如果只是改 URL,韧性逻辑当然也共享,但故障注入的表达力差很多。

**Q:为什么不用 Profile 切换?**
> Profile 是环境概念,mock / real 是依赖概念,两个维度不该绑死。我可能在 prod 配置下
> 临时切到挡板排查一个和 LLM 无关的问题,也可能在 dev 下接真实模型看看 prompt 效果。
> 一个独立的 `llm.mode` 开关让这两个维度正交。

**Q:韧性逻辑为什么不用装饰器模式包在 LlmClient 外面,而是放在一个 Service 里?**
> 本质上 `LlmService` 就是装饰器——它持有一个 `LlmClient`,对外提供加了韧性的同名操作。
> 我没让它实现 `LlmClient` 接口,是因为它的返回类型不同:实现返回原始字符串,外壳返回
> 校验过的枚举加降级信息(`ClassifyOutcome`)。类型不同就不该装成同一个接口,否则调用方
> 拿到一个 `LlmClient` 不知道该不该再校验一次。

**Q:响应模型名为什么要记?配置里不是写了吗?**
> 配置里是我请求的,响应里是供应商实际用的。供应商可能在背后把 `deepseek-chat` 路由到
> 新版本、降级到小模型、或者做 A/B。分类质量突然变化的时候,这两列对不上就是第一个线索。
> 挡板返回 `mock-classifier-v1`,也让日志里一眼能看出这条记录是不是走的挡板。
