# LLM 提示词注入 —— 进度

> 新会话接手:读本文件 → 找第一个非"完成"的里程碑 → 看它的"接手须知"。计划全文 `llm-injection-plan.md`。
> 状态:完成 / 进行中 / 未开始 / 阻塞。每完成一个里程碑立刻 commit 并更新本文件。

| 里程碑 | 内容 | 状态 | commit |
|---|---|---|---|
| M1 | 固化计划(plan + progress) | 完成 | f91e37f |
| M2 | ADR-024 判定口径 + 交叉校验阈值(冻结);test-design/09 | 完成 | (本提交) |
| M3 | 测试集 attacks/controls/裁判词表/label_review.csv + test_dataset.py | 未开始 | |
| M4 | 评测脚本(proxy/runner/judge/report/run_eval,断点续跑,离线重判)+ test_judge/test_report + WireMock 注入桩 + 事实记录用例 | 未开始 | |
| M5 | `--plan` → 试跑 5 次 → 第一阶段正式运行 → 报告 → tag `v0.5-injection-baseline` | 未开始 | |
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
