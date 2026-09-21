# 已知问题与观察项

> 状态列说明:**开放** = 未处理;**已修** = 代码已改且有回归用例;**已决** = 决定不改,ADR 登记差异并有用例钉住;**观察项** = 不是缺陷,记录行为。
> 2026-09-21 修复阶段的处置见文末表格与 [修复后回归验证](修复后回归验证.md)。

> 记录类型:测试体系落地过程中**真实跑出来**的结果(2026-09-20,本机 Windows 11 宿主 + WSL2 Docker)。
> 测试阶段不改被测服务的业务代码(先记录、再在修复阶段处理);这里只记事实、复现方式和挂在测试里的方式,
> 是否修、怎么修在后续阶段决定(见文末表格)。每条都能用文中的用例 id 重跑复现。
>
> 挂法约定:确认是缺陷 / 缺失需求的,对应用例用 `@pytest.mark.xfail(strict=True)` 挂在套件里——
> 一旦服务改了,用例会以 XPASS 变红,提醒同时更新本文件。观察项不挂 xfail,用例按当前行为断言并在标题里注明"观察项"。

## KI-001 工单内容中的手机号未脱敏

| 项 | 值 |
|---|---|
| 严重度 | 中(敏感信息暴露面;规格未要求脱敏,属需求缺失而非实现错误) |
| 发现时间 | 2026-09-20 13:2x 本地跑 `tests/security/test_pii_masking.py` |
| 现象 | 内容 `请回电 13812345678,…` 创建后,创建响应、`GET /api/tickets/{id}`、`GET /api/tickets` 列表、`ticket.content` 列四处原样出现 11 位手机号;同时创建时的分类请求和回复草稿请求把原文原样发给了 LLM 挡板(`/mock/llm/classify`、`/mock/llm/draft` 请求体含手机号)。真实模式下即发给第三方模型供应商 |
| 复现 | `pytest security/test_pii_masking.py -q`;`test_current_behaviour_phone_is_plain` 记录事实(通过),`test_detail_masks_phone` / `test_list_masks_phone` 是期望(xfail strict) |
| 挂法 | xfail(strict),`known_issue` 标记 |
| 备注 | 若决定做脱敏,还要决定"脱敏在哪一层":VO 转换层(接口不露、库里仍明文)、还是入库前(LLM 也拿不到);两者的测试策略不同 |

## KI-002 附件魔数只看文件头,polyglot(合法 PNG 头 + PHP 尾)被接受

| 项 | 值 |
|---|---|
| 严重度 | 低(存下来的文件名是 UUID.png、目录不在 Web 根下、服务不会执行它;前提条件成立时只是"存了个奇怪的 png") |
| 发现时间 | 2026-09-20 13:2x,`tests/security/test_attachment_bypass.py::TestContentLayer::test_polyglot_png_php` |
| 现象 | 内容 = 8 字节 PNG 魔数 + 64 个 0x00 + `<?php echo 'hello from php'; ?>`,文件名 `poly.png`、声明 `image/png` → 201,落盘 |
| 根因 | `FileTypeSniffer.sniff` 只比较前 8 字节魔数(ADR-008 的设计如此),不解析 PNG chunk 结构 |
| 挂法 | xfail(strict) |
| 备注 | 若要收紧,选项是解析图片结构(ImageIO 能否解码)或对图片重新编码后再落盘;两者都会引入新依赖和性能成本,是否值得看附件的消费方是谁 |

## KI-003 上传文件被宿主杀软隔离时,服务返回 500 / 50000

| 项 | 值 |
|---|---|
| 严重度 | 低(环境相关;但错误码语义不准) |
| 发现时间 | 2026-09-20 13:20,traceId `c32223a06e074dcc` / `9a77b5608fd34bd9` / `2913142a70504676` |
| 现象 | 载荷 `<?php system($_GET['c']); ?>` 以 `.jpg` / `.png` 上传(期望 415)和以 `.txt` 上传(期望 201),实际三次全部 **500 / 50000 "服务内部错误"**。服务日志:`java.io.UncheckedIOException: 读取附件头失败 … Caused by: java.nio.file.FileSystemException: C:\Users\…\Temp\tomcat.8080.…\upload_….tmp: 无法成功完成操作,因为文件包含病毒或潜在的垃圾软件。` |
| 根因 | Windows Defender 实时保护把 Tomcat 落到临时目录的 multipart 文件隔离了,`file.getInputStream()` 读不到;`AttachmentService.readHead` 把 IOException 包成 UncheckedIOException,`GlobalExceptionHandler` 兜底成 50000 |
| 复现 | 仅 Windows 宿主 + 开启实时保护;Linux runner 上不出现。套件里的 PHP 载荷已改成无害的 `<?php echo 'hello from php'; ?>` 以测校验层本身(`test_attachment_bypass.py` 文件头注释) |
| 挂法 | 不挂用例(环境相关);记录待决定是否给"附件不可读"单独一个错误码(比如 4xx 而不是 50000) |

## KI-004 声明 MIME 带无法识别的 charset 参数时被拒

| 项 | 值 |
|---|---|
| 严重度 | 低(拒绝方向是安全的) |
| 发现时间 | 2026-09-20 13:20,`test_attachment_bypass.py::TestMimeLayer::test_declared_mime_mismatch[image/png; charset=binary]` |
| 现象 | `Content-Type: image/png; charset=binary` 上传合法 PNG → 415 / 41503,message:`声明的 Content-Type 'image/png; charset=binary' 与扩展名 .png 不符,应为 image/png`。而 `image/png; foo=bar` 放行 |
| 根因 | `AttachmentService.normalizeMime` 调 `MediaType.parseMediaType`,Spring 对 `charset` 参数会 `Charset.forName`,`binary` 不是合法字符集 → 抛异常 → 走 catch 分支把整串小写后原样比较 |
| 挂法 | 用例按当前行为断言(拒绝),标题注明观察项 |

## KI-005 路径参数的容错行为(观察项)

| 项 | 值 |
|---|---|
| 发现时间 | 2026-09-20 13:2x / 16:4x,`tests/security/test_sql_injection.py` |
| 现象 | `GET /api/tickets/1;DROP TABLE ticket` → 200,返回 id=1 的工单(分号后被 Spring MVC 当矩阵变量剥掉);`GET /api/tickets/1%0a`、`1%20` → 200,id=1(Spring 的数字转换会 trim);`GET /api/tickets/1%00` → Tomcat 直接 400,返回的是容器的 HTML 页而不是统一 JSON 信封 |
| 评估 | 都不是注入(MyBatis-Plus 全部预编译,表数量前后不变),但两点值得知道:① 分号剥离意味着 `/api/tickets/1;jsessionid=x` 这类 URL 会被静默接受;② `%00` 的 400 没有 traceId,接口测试对不上日志 |
| 挂法 | `test_path_id_tolerated_suffixes` 按当前行为断言(200/400/404 均可,表不变);`test_path_id_is_typed[nul]` 允许无信封的 400 |

## KI-006 挡板同优先级桩的取舍与关键词规则表顺序不一致(测试设计观察项)

| 项 | 值 |
|---|---|
| 发现时间 | 2026-09-20 13:2x,`test_llm_classify.py::TestNormalClassification::test_ambiguous_keywords` 第一版失败 |
| 现象 | 标题「退款和账单都有问题」:挡板返回 **BILLING**(`llm-classify-rules.json` 里 REFUND / BILLING 两个桩同为 priority 5,WireMock 在同优先级下取后定义的),而关键词规则 `KeywordRuleClassifier` 的 LinkedHashMap 顺序是 REFUND 优先 |
| 评估 | 不是服务缺陷——挡板的取舍不是规格。但它意味着"正常路径"和"降级路径"对同一句话可能给出不同分类;如果某天真实模型也这样,`llm_call_log.raw_category` 与规则结果的差异就是排查线索 |
| 挂法 | 用例改为只断言"在枚举内且未降级",不断言具体类别 |

## KI-007 带标签的指标在首次发生前不存在(可观测性观察项)

| 项 | 值 |
|---|---|
| 发现时间 | 2026-09-20 13:1x,服务刚启动时 `test_health_auth.py::test_custom_metrics_exposed` 第一版失败 |
| 现象 | `/actuator/prometheus` 在服务启动后没有 `llm_fallback_total`、`llm_circuit_open_total`、`llm_contract_violation_total`、`llm_call_duration_seconds`;第一次降级 / 熔断 / 越界发生后才出现对应标签组合的序列。构造器里 `register` 过的 `llm_circuit_state`、`sla_*`、`mq_event_*` 一直在 |
| 评估 | Micrometer 带 tag 的 Counter 是惰性创建的。对 Grafana 意味着重启后面板是 "No data" 而不是 0,`increase()`/`rate()` 在第一次出现的那个采样点会算不出来 |
| 挂法 | 用例只断言启动即存在的那组;若希望面板从 0 开始,需要在 `LlmMetrics` 里预注册全部 reason / scene 组合 |
| 2026-09-21 | **已修**:`LlmMetrics` 构造时预注册 2 场景 × 4 原因 + circuit_open + contract_violation,`test_labelled_llm_counters_pre_registered` 断言启动即为 0 |

---

## 未列入的项(核对过,不是问题)

- `spring.servlet.multipart.max-file-size=8MB` 大于业务上限 5MB:有意为之(README §7),让 5MB~8MB 之间的文件由业务层返回 41301 而不是容器层的 413。8MB+1 由容器拦(`MaxUploadSizeExceededException`),响应 413,已验证(`test_oversize` 只断了状态码,业务码未单独断)。

---

## 压测与故障注入阶段(2026-09-20 17:53~21:56)新增,及修复阶段(2026-09-21)的处置

| 编号 | 一句话 | 记录 | 2026-09-21 状态 |
|---|---|---|---|
| KI-008 | 抢单 check-then-act 竞态:2 线程即 100% 复现,N 个 200、assignee 被覆盖 | [20260920-压测-抢单并发重复分配](20260920-压测-抢单并发重复分配.md) | **已修**(ADR-016):条件 UPDATE + version + Redis 前置锁;回归 2×5 / 20 / 100 线程及 Redis 停机下恰 1 个 200;门禁 `test_concurrency.py` |
| KI-009 | 审计 `from_status` 取自 SELECT 时刻的内存快照,并发下记录出未发生的 `PENDING→ASSIGNED` | [20260920-压测-审计日志记录未发生的状态转换](20260920-压测-审计日志记录未发生的状态转换.md) | **已修**(ADR-017):from 只在 UPDATE 命中 1 行后写,SLA 升级带 status/version;反向断言 `assert_audit_chain` 全库 0 断裂 |
| KI-010 | 同一并发得到不同成功数——HikariCP 池随 idle-timeout 收缩;压测数字必须带环境状态 | [20260920-压测-同一并发不同成功数-连接池历史状态](20260920-压测-同一并发不同成功数-连接池历史状态.md) | **已决**(ADR-021 / ADR-022):不固定池;并发用例前预热、只断言正确性;平台比较器把环境不同判为不可信 |
| KI-011 | `ticket_no` 32 bit 随机量,日创建 ~9 万张时生日碰撞 → 500(实测 2 次) | [20260920-压测-性能拐点与瓶颈 §5.3](20260920-压测-性能拐点与瓶颈.md) | **已修**(ADR-019):64 bit;同档位 21001 张 0 错误;单测 100 万次 0 重复 |
| KI-012 | MQ 消费端 ≈190 条/s,生产 > 20 线程即积压,最高 52k 条 | 同上 §5.1 | **开放**(配置容量问题):`test_capacity.py` 钉住"不丢、预算内清空",速率每次记入报告 |
| KI-013 | SLA 调度器 100 张 / 30 s,到期高峰积压数小时 | 同上 §5.2 | **开放**:`test_capacity.py` 钉住"每轮 ≤ batch、每张恰 1 次",换算时间记入报告 |
| KI-014 | RabbitMQ 不可用期间提交的事件永久丢失、不补投,与任务书"不丢、补投"矛盾 | [20260920-故障注入记录 §2](20260920-故障注入记录.md) | **已决**(ADR-018):选丢失可观测、不补投;用例断言 publish_failed / ERROR 日志 / 恢复后**无补投** |
| KI-015 | Redis 恢复 23.6 s 重连;熔断定值 60 s,依赖恢复后最多再降级 60 s | 同上 §1 / §3 | **已决**(ADR-020):SLO 45 s / 60 s 写成用例,实测秒数记入 Allure |
| KI-016 | Tomcat 线程池指标未暴露;文件日志无 traceId;带标签 LLM 指标首次发生前不存在 | 本轮压测过程 | **已修**:`mbeanregistry.enabled`、file pattern 带 traceId、`LlmMetrics` 构造预注册;`test_health_auth.py` 断言 |
| **KI-017** | 列表接口 `GET /api/tickets?status=` 的 `COUNT(*)` 走 `idx_ticket_status_sla` 扫 4 万索引项再回表核对 `deleted`,10 万张单时单核 ≈53 次/s 封顶,读链路 10 线程即到平台(list p50 152 ms) | [修复后回归验证 §5](修复后回归验证.md) | **开放**(只写不改):候选覆盖索引 `(status, deleted, id)` / 不返回精确 total / 缓存 total |
