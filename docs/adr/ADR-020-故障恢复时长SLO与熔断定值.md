# ADR-020: 依赖恢复后的"回到正常"要有 SLO——Redis 45 s、RabbitMQ 45 s、LLM 熔断固定 60 s 不探测

## 背景

故障注入([记录](../findings/20260920-故障注入记录.md))测出了三个"恢复后还要再等一会儿":
Redis `docker start` 后 Lettuce 重连用了 23.6 s,期间每请求仍 +1 s;RabbitMQ 恢复后监听容器 11 s 重连;
LLM 挡板恢复后熔断器仍固定降级到 60 s 到期才闭合。三者都"按设计",但设计里没写"多久算正常",
README / ADR 只写了"停机时不 500",没写"恢复后多久回到基线"(KI-015)。没有数字的恢复承诺等于没有承诺。

## 选项

- **方案 A:给每个依赖一个恢复 SLO,写成用例,把实测秒数记进报告** ← 采用
  做法:配置 `redis_recovery_slo_seconds=45`、`rabbit_recovery_slo_seconds=45`(`tests/api/framework/config.py`);
  `test_fault_injection.py` 在 `docker compose start` 之后计时,等到 health UP 且鉴权延迟 < 200 ms(Redis)/
  新消息被消费(RabbitMQ),超过 SLO 即失败,实测秒数挂进 Allure。LLM 熔断:`test_llm_circuit.py` 增加一条
  "挡板已健康、熔断打开 30 s 后仍降级",把"最坏再降级 60 s"写成显式接受。
  阈值怎么定:Redis 实测 23.6 s,Lettuce 默认重连退避指数增长到 30 s 封顶,最坏一次退避 30 s + 连接建立,
  45 s 是"默认退避的上界 + 余量",不是拍脑袋;RabbitMQ 实测 11 s,Spring AMQP 监听容器 `recoveryInterval`
  默认 5 s,45 s 留了 4 倍余量给 CI 上更慢的容器启动。
  代价:阈值是本机和 CI 的经验值,换环境要重测;用例每条 40~60 s。

- 方案 B:调短重连退避,把恢复时间压到几秒
  做法:Lettuce `ClientOptions` 自定义 `ReconnectionPolicy`,RabbitMQ `recoveryInterval` 调到 1 s。
  代价:退避存在的意义是别在依赖挂掉时用重连风暴把它压死;调短是在"恢复快"和"雪崩风险"之间挪位置。
  本项目单实例,调短没有风险,但这是运行时行为的改动,应该由 SLO 用例先量出来"现在是多少"再决定要不要改——
  先测量,后调参。

- 方案 C:熔断器改成半开探测(open 期间每 N 秒放一个请求试探)
  做法:`CircuitBreaker` 加 HALF_OPEN 状态。
  代价:ADR-004 已经讨论过并放弃:半开探测的那一个请求要承担 3 s 超时,并且"恢复"与否要连续成功几次才算,
  状态机从 2 态变 3 态,测试组合翻倍。60 s 定值换来的是行为可预测:恢复后最坏多降级 60 s,
  降级期间走的是规则分类,结果可用只是不智能。

## 决定

方案 A。三个数字进契约:

| 依赖 | 恢复的定义 | SLO | 2026-09-20 实测 | 用例 |
|---|---|---|---|---|
| Redis | health UP 且 `/api/agents/me` < 200 ms | 45 s | 23.6 s | `TestRedisOutage::test_fail_open_and_recovery_within_slo` |
| RabbitMQ | health rabbit=UP 且新消息被消费(去重表有行) | 45 s | ≈11 s | `TestRabbitOutage::test_publish_failure_is_observable_and_not_replayed` |
| LLM 挡板 | 熔断器闭合、正常标题重新由模型分类 | 恢复后 ≤ 60 s(定值,不探测) | 挡板恢复后 +49 s 仍 open,+77 s 闭合 | `TestCircuitBreaker::test_still_degraded_while_dependency_is_healthy` + `test_recovers_after_open_window` |

方案 B 留作后续:SLO 用例先跑几轮把分布记下来,再决定要不要调退避。

## 后果

- 接受:三条用例合计约 2.5 分钟,且必须排在会话最后(中间件停机期间跑别的用例无意义)。
- 接受:SLO 是上界不是目标;CI runner 上 Redis 容器冷启动可能更慢,阈值给了余量但没有验证过 GitHub Actions 的分布,
  第一次在 CI 上红了要看实测值再调,不要直接放宽。
- 什么场景下这个选择会是错的:多实例部署时"恢复"还包括实例间的一致性(锁、缓存),单实例的 SLO 不够用。

## 常见质疑与回应

**Q:45 秒是怎么来的?为什么不是 30 或 60?**
> 从机制推的:Lettuce 的默认重连策略是指数退避、30 s 封顶,最坏情况是一次 30 s 的等待加上连接建立,
> 实测 23.6 s 正好落在这个区间。45 = 30 的上界 + 50% 余量。RabbitMQ 监听容器默认 5 s 一次重试,实测 11 s,
> 45 s 是给 CI 上更慢的容器启动留的。它不是目标值,是"超过这个数说明有别的问题"的报警线。

**Q:既然知道 Lettuce 退避到 30 s,为什么不直接调短?**
> 先测量后调参。退避是为了防重连风暴,单实例下调短没有风险,但我想先让 SLO 用例跑几轮,
> 看恢复时间的分布是不是稳定在 20 多秒;是的话调短是收益明确的一行配置,不是的话先找原因。
> 没有测量就调参,下次故障时不知道是参数的功劳还是运气。

**Q:熔断器恢复后还要再降级最多 60 秒,这不是缺陷吗?**
> 是接受的代价,现在有用例把它写成显式契约。半开探测能缩短这 60 秒,代价是状态机从 2 态变 3 态、
> 探测请求要承担 3 s 超时、"恢复"需要连续成功几次的判定,测试组合翻倍。降级期间走关键词规则,结果可用只是不智能,
> 60 秒的不智能换行为可预测,我认为值。如果这 60 秒变成业务问题——比如分类准确率直接影响 SLA 优先级——
> 再上半开。

**Q:这些用例在 CI 上稳吗?docker stop 中间件很容易 flaky。**
> 三点保证:排在会话最后,不影响别的用例;每一步都是 wait_until 等条件而不是 sleep 固定秒数;
> SLO 阈值留了余量。第一次在 CI 红了,看 Allure 里记录的实测秒数——如果是 50 s 就是环境慢,
> 如果是超时没恢复就是真问题。用例的价值正是把"多久"这个数字每次都记下来。
