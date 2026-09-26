# LLM 提示词注入 —— 交接(2026-09-26,tag `v0.6-injection-defense`)

> 计划 `llm-injection-plan.md`,逐步日志 `llm-injection-progress.md`。本文件只写"现在是什么状态、数字在哪、还剩什么要作者决定"。
> 所有数字都能由仓库里的命令从已录制的 raw 重新算出来,本文不重复抄数,只给索引和一句话结论。

## 1. 做完了什么

| 阶段 | 结果 | 在哪 |
|---|---|---|
| 第一阶段基线(无防御) | 538 次真实调用,四类注入都成功过(A 翻转 16/60、B 15/50、C 人工核对后 31/50、D 16/40);另测出解析漏洞 KI-022 | `reports/phase1-20260925T102100Z/`、findings/20260925 基线、KI-018~022 |
| 第二阶段防御 | 输入隔离(`UntrustedInput` + 提示词追加句)、交叉校验、草稿输出检查、严格解析(恰好一个 JSON 对象;夹带 → `MIXED_OUTPUT` 不计入熔断,读不出 → `BAD_RESPONSE` 计入) | ADR-024 第二阶段防御一节、判定表 03、walkthrough 第 17 节 |
| v1 复测(唯一一次正式运行) | 538 次;四类攻击在模型层与端到端都是 0;输出侧防线对攻击 0 次触发;交叉校验误伤 13 次(KI-023) | `reports/phase2-v1-20260926T040541Z/`(report.md、compare.md、hit_review.csv)、findings/20260926 防御后复测 |
| 留出集工具 | 一条命令在防御前 / 后各跑一次并出对比报告;`-SmokeTest` 已在本机跑通 | `tests/llm_security/tools/holdout_compare.ps1`、`tests/llm_security/README.md`「留出集」 |

复现(都不发请求):

```bash
python tests/llm_security/run_eval.py rejudge tests/llm_security/reports/phase2-v1-20260926T040541Z
python tests/llm_security/run_eval.py compare tests/llm_security/reports/phase1-20260925T102100Z tests/llm_security/reports/phase2-v1-20260926T040541Z
python tests/llm_security/run_eval.py format-split tests/llm_security/reports/phase1-20260925T102100Z tests/llm_security/reports/phase2-v1-20260926T040541Z
```

## 2. 已知局限(读 v1 的"0"之前必须知道)

1. **攻击集与防御同源**:40 条攻击样本和第二阶段防御都由 Claude 编写,防御后的数字偏乐观。
2. **防御设计者读过第一阶段数据**(ADR-024 第二阶段防御一节的披露):写防御的 Claude 在 M5.5 人工核对时逐条读过第一阶段全部 90 份 C/D 草稿,
   知道模型成功时写了什么。防御的词表、窗口、阈值没有拿录到的数据试算过,但"没调过"只能保证到这一步,不能保证设计者的直觉没被数据影响。
   这条同时写在 v1 的 report.md 顶部、compare.md 顶部、findings/20260926 顶部。
3. **样本量**:k = 5、40 条攻击;按样本 0/12 的单侧 95% 置信上限约 22%。
4. **时段**:两次运行相隔约 18 小时;响应 model 名与 `system_fingerprint` 都相同,但"防御的作用"和"同一模型不同时段的波动"在设计上没有完全隔开
   (隔开的办法见 §4-3)。**2026-09-26 已做基线复跑(只跑攻击样本)**:防御前代码在 v1 后 4.4 小时复现了第一阶段的成功率,见 `tests/llm_security/reports/phase1-rerun-attacks-20260926T083123Z/rerun_compare.md`。
5. **标签与核对都未经作者审**:72/72 样本 `model_labeled`;C/D 人工核对由 Claude 完成(v1 规则 0 命中、通读 90 份草稿未标漏判,两条边界草稿写在 findings §5)。
6. **留出集还没跑**:`data/holdout.jsonl` 为空。它是唯一不同源的检验。

## 3. 留出集(作者亲手编写,防御定稿之后)

- 这组样本**必须在防御定稿之后由作者亲手编写**——写防御的 Claude 没见过它们,这是它和 phase1 / phase2 对比的根本区别。Claude 没有替作者写,也没有等。
- 格式与 `attacks.jsonl` 相同,要点见 `tests/llm_security/README.md`「留出集」;写完先跑离线用例(`cd tests/llm_security && python -m pytest`),
  `test_holdout_is_valid_together_with_dataset` 会在花真实调用之前挡住格式错误。
- 一条命令(仓库根目录 PowerShell;key 只在这个进程里从文件读入,计划 §2-7):

  ```powershell
  powershell -ExecutionPolicy Bypass -File tests\llm_security\tools\holdout_compare.ps1 -KeyFile 'D:\个人\api(Deepseek).txt' `
    -JavaHome D:\tools\jdk-17 -Maven D:\tools\maven\bin\mvn.cmd -Python E:\python\python.exe
  ```

  防御前 = tag `v0.5-injection-baseline` 的服务代码(临时 worktree 打包),防御后 = 当前工作区;报告 `reports/holdout-post-*/compare.md`。
  跑之前 `python tests/llm_security/run_eval.py plan --holdout` 看两次合计的调用数;预算余 1700 − 1086 = 614。
- 不要把脚本输出接管道(最后重启的服务会继承管道句柄,调用方一直等);要日志就重定向到文件。

## 4. 等作者决定的事

1. **KI-023 交叉校验误伤**(最重要):冻结阈值"模型 P0 且规则 P2 → 采用规则"在规则什么都没认出来时把真 P0 降成 P2。候选:
   ① 只在规则至少命中一个类别时才判优先级冲突;② 冲突时只标复核、不改采用值。两者的误伤可用 v1 raw 里的 `rule_category / rule_priority` 离线算。
   改了就是 v2,需要再完整跑一次 538(与留出集抢预算)。ADR-024 质疑与回应一节有两种改法各自的代价。
2. **标签审核**:`labels apply --csv tests/llm_security/data/label_review_priority.csv`(15 行)→ 对 phase1、phase2-v1 各 `rejudge`,再 `compare`。
   注意 N-017、N-026 两条 ⚠ 对照正是 KI-023 的受害者,"剔除 ⚠"版本会把误伤藏掉。
3. **是否同时段重跑防御前代码**:用 `v0.5-injection-baseline` 的服务对攻击集再跑一次(538 次),把"时段波动"从 v1 的 0 里分离出来。会占掉留出集的预算。
4. **SLA 用例的时钟偏差**:全量回归 3 条 `test_sla.py::TestEscalation` 失败,原因是 WSL 里 MySQL 的时钟比宿主快约 1.4 s(findings/20260926 §7)。
   `wsl --shutdown` 后重起中间件通常能消除;用例"只用 DB 时钟"的假设在服务用宿主时钟时不成立,要不要改用例由作者定(已在会话里留了一个独立任务建议)。

## 5. 环境现状

- 服务:挡板模式在跑(pid 见 `logs/app.pid`),jar 为 v1 前 `mvn clean verify` 打出(= c721940 的服务代码)。本机 MySQL 已有 V3 迁移。
- 真实调用累计 1086 / 1700(`tests/llm_security/reports/call_budget.json`)。
- API key:文件路径已写进计划 §2-7;key 本身没有进入仓库、日志或任何报告(提交前对运行目录与 `logs/phase2.log` 搜过 `sk-` 前缀,0 处)。
- 未 push;本地 tag `v0.5-injection-baseline`、`v0.6-injection-defense`。
