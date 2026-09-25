# LLM 提示词注入 —— 进度

> 新会话接手:读本文件 → 找第一个非"完成"的里程碑 → 看它的"接手须知"。计划全文 `llm-injection-plan.md`。
> 状态:完成 / 进行中 / 未开始 / 阻塞。每完成一个里程碑立刻 commit 并更新本文件。

| 里程碑 | 内容 | 状态 | commit |
|---|---|---|---|
| M1 | 固化计划(plan + progress) | 完成 | f91e37f |
| M2 | ADR-024 判定口径 + 交叉校验阈值(冻结);test-design/09 | 完成 | f094bb1 |
| M3 | 测试集 attacks/controls/裁判词表/label_review.csv + test_dataset.py | 完成 | 3135728 |
| M4 | 评测脚本(proxy/runner/judge/report/run_eval,断点续跑,离线重判)+ test_judge/test_report + WireMock 注入桩 + 事实记录用例 | 完成 | 63559d4 06d4319 252d548 155af96 |
| M5 | `--plan` → 试跑 5 次 → 第一阶段正式运行 → 报告 → tag `v0.5-injection-baseline` | **阻塞:停止条件 1(LLM_API_KEY 不存在)** | — |
| M6 | 按实测登记 KI-018 起 + xfail(strict) 期望用例;findings 基线篇 | 未开始(以后会话) | |
| M7 | 第二阶段防御代码 + 单测 + WireMock 用例转正(必须在 M5 之后) | 未开始(以后会话) | |
| M8 | 第二阶段复测(只一次正式运行 v1;需要时 v2 最多一次)+ compare | 未开始(以后会话) | |
| M9 | 文档收尾:ADR-024 补全、findings、test-inventory、README、walkthrough、test-design/03;tag `v0.6-injection-defense` | 未开始(以后会话) | |
| M10 | handoff | 未开始(以后会话) | |

## 真实调用累计

| 时间 | 运行 | 次数 | 累计 |
|---|---|---|---|
| — | — | 0 | 0 |

(上限 1300,超过即停。runner 也在 `tests/llm_security/reports/call_budget.json` 里持久化计数。)

## 接手须知 / 日志

- 2026-09-25 M1:计划确认,决定见 plan §3。
- 2026-09-25 M2:ADR-024 只写了"判定口径""交叉校验阈值"两节并冻结;其余五节第二阶段补。test-design/09 完成。
- 2026-09-25 M3:数据集 40 攻击 + 32 对照,文本指纹见 `python -c "from llmsec import dataset as d; print(d.load().text_sha256())"`(在 tests/llm_security 下)。离线用例 `cd tests/llm_security && python -m pytest`(独立 pytest.ini,不加载 tests/conftest.py)。ADR-024 §5 的 ⚠ 继承范围在开跑前细化为:A/B 继承基底,C/D 不继承。样本由一次性脚本生成,jsonl 本身是源,之后只通过 labels apply 改标签。
- 2026-09-25 M4:`tests/llm_security` 离线用例 87 条(独立 pytest.ini,CI api job 里单独一步);`tests/security/test_prompt_injection.py` 4 条事实记录用例 + `ops/wiremock/mappings/llm-injection.json`。runner 断点续跑按 key 去重;连续 3 次上游失败 → failures.jsonl → 等 60 s 重试 → 仍失败停;预算计数 `tests/llm_security/reports/call_budget.json`。服务在本机用 `D:\tools\jdk-17\bin\java.exe` 启动(java 不在 PATH;命令见 tests/llm_security/README.md,java.exe 换成全路径)。
- 2026-09-25 M4 回归(挡板模式,池 20):`pytest` 全量 311 passed / 3 xfailed / 2 failed。① `test_state_machine.py::TestLegalPaths::test_escalated_back_to_assigned` 单独重跑通过(偶发);② `test_capacity.py::TestConsumerStarvation::test_consumer_not_starved_when_pool_saturated` 在池 20 和按 ADR-023 的池 3 下各重跑一次仍失败:断言 `consumed_delta >= published_delta` 时消费计数落后(池 3:61 vs 1324),但用例结束后指标 `mq_event_consumed_total = mq_event_published_total = 2990`、`mq_event_duplicate_total = 0`——消息没丢,是"积压清空"判断(RabbitMQ 管理接口 `messages` 采样统计)早于消费计数追平。本次改动没有碰 `service/`、迁移、`tests/api/`,判定与本任务无关,**未改该用例**,留给作者决定(候选:等待条件改成两个计数相等)。
- 2026-09-25 M5:`run_eval.py plan` 输出 A/B 分类 110 · 对照分类 160 · C/D 建单 18 · C/D 草稿 90 · 对照草稿 160 · 合计 538,试跑 5(与计划 §4 一致)。`run_eval.py pilot` 在前置检查处停止:**停止条件 1——环境变量 `LLM_API_KEY` 在进程 / 用户 / 系统三级都不存在**。未发出任何真实请求,真实调用累计仍为 0。
- 2026-09-25(第二次会话)作者授权从本机文件读 key(约束见 plan §2-7,key 不入仓库)。
- 2026-09-25 插入任务 1:修复容量用例 `test_consumer_not_starved_when_pool_saturated` 的"积压清空"判断(改为消费计数追平发布计数,核心断言不变)。池 3 下修改前 3 次 1 过 2 败(74<1240、899<1298),修改后 3/3 通过。记为测试自身缺陷:`docs/findings/20260925-测试缺陷-容量用例积压清空判断用了采样统计.md`,known-issues 末尾"测试自身缺陷"表。

## M5 接手步骤(作者设好 `LLM_API_KEY` 之后)

1. 确认中间件在跑(WSL compose),`service/target/ticket-qa-service-0.1.0.jar` 已是最新(2026-09-25 重新打过包,服务代码第一阶段未改)。
2. 停掉当前挡板模式的服务(pid 在 `logs/app.pid`),在**带 `LLM_API_KEY` 的同一个 PowerShell 里**按 `tests/llm_security/README.md` 第 2 步以真实模式启动(java 用 `D:\tools\jdk-17\bin\java.exe` 全路径;`LLM_BASE_URL=http://127.0.0.1:18090`;`--llm.timeout-ms=30000 --llm.circuit.failure-threshold=100000`)。
3. 同一个 shell 里:`python tests/llm_security/run_eval.py pilot` → 输出"试跑检查通过"后 → `python tests/llm_security/run_eval.py run --phase phase1`(后台跑,输出落盘,每 5 分钟最多看一次进度)。
4. 若试跑里上游拒绝了模型名(计划 D2):`run_eval.py models` → 选 flash 模型 → 以 `LLM_MODEL=<它>` 重启服务 → 重新 pilot;把选择写进 meta(自动)和 ADR-024。
5. 中断后:`run --phase phase1 --resume tests/llm_security/reports/phase1-<UTC>`,已完成的调用不会重复。
6. 跑完 report.md 自动生成 → 提交 `reports/phase1-*` 与 `reports/call_budget.json` → tag `v0.5-injection-baseline`。
7. 回到挡板模式:`LLM_MODE=mock` 重启服务(接口自动化默认走挡板)。
