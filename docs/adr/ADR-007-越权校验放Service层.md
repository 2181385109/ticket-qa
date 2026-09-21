# ADR-007: 认证简化为 X-User-Id 头,授权(越权校验)全部放在 Service 层

## 背景

三种角色:AGENT 只能读写分配给自己的工单,LEADER 能读写本组并改派,ADMIN 全权。
CLAUDE.md §5.6 要求越权校验放 Service 层,因为它是水平越权 / 垂直越权安全用例的载体。
另外要决定:这个测试系统需要多强的"认证",以及越权时返回 403 还是 404。

## 选项

### 认证(你是谁)

- **方案 A:Spring Security + JWT / Session**
  代价:登录接口、密码存储、token 签发与校验、过滤器链配置——一整套和"工单质量保障"
  无关的东西,而且 Spring Security 的过滤器链是与主题无关的复杂度。不在锁定的技术栈里。

- **方案 B:`X-User-Id` 请求头 → 查坐席表 → 放进 ThreadLocal** ← 采用
  做法:`AuthInterceptor` 读头、经 `AgentService`(Redis 缓存)拿到 `CurrentUser`、
  放进 `UserContext`(ThreadLocal),`afterCompletion` 清掉。头缺失或坐席不存在 / 停用 → 401。
  代价:任何人都能伪造 `X-User-Id: 1` 变成 ADMIN。这个测试系统的被测点是**授权逻辑**
  是否正确,不是认证强度;伪造头恰恰是安全用例需要的能力(用 AGENT 的 id 访问别人的单)。

### 授权(你能不能)放哪一层

- **方案 A:Controller 层用注解(`@PreAuthorize`)或手写判断**
  代价:只能表达"角色是否够"(垂直),表达不了"这张工单是不是你的"(水平)——
  水平越权需要先查出工单再比对 assignee / group,这是 Service 的事。而且 Controller 拦了,
  定时任务、MQ 消费者、以后的内部调用绕过 Controller 就没有校验。

- **方案 B:Service 层调用 `AccessChecker`** ← 采用
  做法:每个 Service 方法先 `UserContext.require()` 拿当前用户,`getOrThrow(id)` 取工单,
  再 `access.checkRead / checkWrite / checkGrab / checkAssign`。Controller 里没有任何权限代码。
  规则集中在 `AccessChecker` 一个类里,是安全用例的判定表来源。
  代价:每个 Service 方法多两行;测试 Service 时要先设置 `UserContext`。

### 越权返回什么

- **方案 A:404(不泄露存在性)**
  安全最佳实践之一:水平越权时返回 404,让攻击者无法枚举工单是否存在。
- **方案 B:403,水平和垂直用不同错误码** ← 采用
  做法:水平越权 `FORBIDDEN(40301)`,垂直越权 `ROLE_FORBIDDEN(40302)`。
  理由:这是测试系统,安全用例需要**精确断言**拦截发生在哪一层、因为什么原因。
  404 会让"工单不存在"和"不是你的工单"混在一起,用例区分不了。

### 规则细节(默认选择)

| 操作 | AGENT | LEADER | ADMIN |
|---|---|---|---|
| 读 / 改 / 流转 | assignee == 自己 | 工单在本组 | 全部 |
| 抢单 | 工单在本组且 PENDING | 同左 | 全部 |
| 指派 / 改派 | 不行(ROLE_FORBIDDEN) | 工单在本组,目标坐席也在本组 | 目标坐席与工单同组 |
| 删除 | 不行 | 不行 | 可以(逻辑删除) |
| 手动触发 SLA 扫描 | 不行 | 不行 | 可以 |
| 创建工单 | 可以 | 可以 | 可以 |
| 列表 | 自动过滤 assignee=自己 | 自动过滤 group=本组 | 全部 |

LEADER "能读本组、能改派"被解释为"本组工单可读可写可改派"——组长处理本组工单是合理的。
如果认为 LEADER 只读 + 改派、不能自己流转,把 `AccessChecker.canAccess` 里 LEADER
分支拆成读写两条即可。

## 决定

- 认证:`X-User-Id` 头,拦截器只拦 `/api/**`,Actuator 不拦。
- 授权:全部在 Service 层,通过 `AccessChecker`。
- 水平越权 403 + 40301,垂直越权 403 + 40302,未认证 401 + 40101。
- 当前用户放 ThreadLocal,拦截器 `afterCompletion` 必须清理。

## 后果

- 接受:认证可伪造。README 里明确写"不是生产级鉴权"。
- 接受:403 泄露存在性。生产系统应改 404,但那时安全用例要改断言。
- 接受:ThreadLocal 在异步场景(`@Async`、线程池)里不会自动传播;本项目没有异步业务调用,
  MQ 消费者和定时任务不需要当前用户(它们的操作者是 SCHEDULER / 系统)。
- 什么场景下会是错的:对外暴露的生产系统。那时需要真正的认证,`AuthInterceptor` 换成
  Spring Security 的过滤器,但 `AccessChecker` 和 Service 层校验不需要动——这正是把授权
  放 Service 层的收益。

## 常见质疑与回应

**Q:为什么不用 Spring Security?**
> 因为我要测的是授权逻辑——AGENT 能不能看别人的单——不是认证强度。Spring Security 解决的
> 是"证明你是谁",一整套过滤器链、密码编码、token 签发,和工单业务无关,却与被测点
> 无关。X-User-Id 头让安全用例可以直接扮演任何角色,这是测试系统需要的能力。
> 而且我把认证和授权拆开了:换成 Spring Security 只需要替换拦截器,Service 层的
> AccessChecker 一行不用改。

**Q:越权校验为什么不在 Controller 拦?那里拦不是更早、更省?**
> Controller 只知道请求参数,不知道这张工单属于谁——水平越权必须先查出工单再比对
> assignee 或 group,这个信息在 Service 层才有。而且 Controller 只是入口之一:定时任务、
> MQ 消费者、以后的内部 RPC 都不经过 Controller,校验放 Controller 等于给这些入口开了后门。
> Service 层是所有入口的汇合点,校验放这里才是"每条路都要过安检"。

**Q:越权返回 403 不是泄露了工单存在?应该 404。**
> 生产系统我同意用 404。这里我有意选 403 并且水平、垂直用不同错误码,因为这是测试系统,
> 安全用例要精确断言"拦截发生在哪一层、因为什么"。404 会把"不存在"和"不是你的"混在
> 一起,用例就退化成"反正没拿到数据"。这个取舍写在 ADR 里,改回 404 是一行代码加一批
> 用例断言的事。

**Q:ThreadLocal 有什么坑?**
> Tomcat 线程池复用线程,请求结束不清理的话,下一个落到这个线程的请求会"继承"上一个
> 用户——这是最常见的越权 bug 来源之一。我在拦截器 afterCompletion 里 remove,它在
> 响应写完后一定执行,包括 Controller 抛异常的情况。另一个坑是异步:`@Async` 起的新线程
> 拿不到 ThreadLocal,本项目没有这种调用,有的话要用 TaskDecorator 传递。
