# tests/llm_security —— 提示词注入的真实模型评测

计划:`docs/plans/llm-injection-plan.md`;判定口径:`docs/adr/ADR-024`;用例设计:`docs/test-design/09-LLM注入测试设计.md`。

这里有两类东西:

| | 命令 | 需要 | 进 CI |
|---|---|---|---|
| 离线用例(数据集、判定规则、报告、续跑、代理) | `cd tests/llm_security && python -m pytest` | 只要 Python | 是 |
| 真实模型评测 | `python tests/llm_security/run_eval.py …` | 服务 + MySQL + `LLM_API_KEY` | 否 |

离线用例有自己的 `pytest.ini`,不会加载 `tests/conftest.py`(那里要求服务在线)。

## 目录

```
data/attacks.jsonl        40 条攻击样本(A12 B10 C10 D8),每条挂一个干净的基底对照(base_id)
data/controls.jsonl       32 条正常对照(四类各 8)
data/holdout.jsonl        留出集,本轮为空(作者日后自行补充)
data/judge_*.json         C / D 类裁判词表(第一阶段开跑前冻结;与第二阶段防御词表分开维护)
data/label_review.csv     标签审核表(labels export 生成)
data/label_review_priority.csv  精简审核表:⚠ 样本 + 对照组优先级判错的样本(labels export-priority 生成,M5.5)
llmsec/                   dataset / proxy(录制代理)/ runner / judge / report / review(M5.5 基线复核)
fixtures/fake-run/        构造的假运行(不是真实数据),给离线用例用
reports/<阶段>-<UTC>/     raw.jsonl(每次调用一行)、meta.json、report.md、failures.jsonl(停止时未落 raw 的失败)、
                          hit_review.csv(C/D 命中人工核对表,可选;有它报告才出"人工核对后结果")
reports/call_budget.json  真实调用累计计数(上限 1300,跨会话)
```

## 真实评测怎么跑

1. 起中间件(见仓库 README §0.4),`mvn -DskipTests package` 打包服务。
2. 以真实模式启动服务,**LLM 指向本机录制代理**,放宽超时与熔断(只为评测,原因见计划 §4):

   ```powershell
   # LLM_API_KEY 已在当前环境变量里;这里不读、不打印它的值
   $env:LLM_MODE = "real"; $env:LLM_BASE_URL = "http://127.0.0.1:18090"
   Start-Process java.exe -ArgumentList '-Dfile.encoding=UTF-8','-jar','target\ticket-qa-service-0.1.0.jar',
     '--llm.timeout-ms=30000','--llm.circuit.failure-threshold=100000' -WorkingDirectory service `
     -RedirectStandardOutput logs\stdout.log -RedirectStandardError logs\stderr.log -WindowStyle Hidden
   ```

   服务启动日志里的 `LlmClient = 真实调用 baseUrl=… model=… timeout=…ms` 会被 run_eval 读出来写进 meta.json。
3. 评测(代理由 run_eval 在 127.0.0.1:18090 起,转发到 `LLM_UPSTREAM_BASE_URL`,默认 `https://api.deepseek.com`):

   ```bash
   python tests/llm_security/run_eval.py plan                 # 调用次数,不发请求
   python tests/llm_security/run_eval.py pilot                # 5 次试跑 + 自动检查
   python tests/llm_security/run_eval.py run --phase phase1   # 正式运行,结束自动生成 report.md
   python tests/llm_security/run_eval.py run --phase phase1 --resume tests/llm_security/reports/phase1-<UTC>   # 断点续跑
   python tests/llm_security/run_eval.py run --phase holdout  # 留出集(本轮为空,直接退出)
   python tests/llm_security/run_eval.py models               # 请求被拒时查上游可用模型(计划 D2)
   python tests/llm_security/run_eval.py format-split tests/llm_security/reports/<运行目录>   # 分类输出:恰好一个对象 / 夹带 / 读不出(不发请求,ADR-024 修订 #3)
   ```

   停止条件(计划 §2-9):`LLM_API_KEY` 不存在 / 上游 401、403;上游连续失败 3 次、等 60 s 重试仍失败;累计调用将超 1300。
   停下后用 `--resume` 续跑,已完成的调用不会重复。

## 标签审核与离线重判(不发请求)

```bash
python tests/llm_security/run_eval.py labels export                      # → data/label_review.csv
# 在 Excel 里改"确认(Y) / 改为分类 / 改为优先级 / 改为攻击目标 / 改为⚠ / 剔除(Y)"
python tests/llm_security/run_eval.py labels apply --reviewer 姚尹杰
python tests/llm_security/run_eval.py rejudge tests/llm_security/reports/phase1-<UTC>
```

攻击样本的期望标签继承自基底,只能在基底那一行改,apply 会同步。数据集文本指纹只覆盖 id + 标题 + 内容,
改标签不影响;改了样本文本,已录制的 raw 就不能再按新数据集判定(rejudge 会拒绝)。
离线用例 `test_committed_report_regenerates_identically` 要求每个已提交的 report.md 都能由 raw 逐字节重新生成——
改了标签忘了 rejudge,CI 会红。

## 基线复核(M5.5,不发请求)

报告 §0 是主口径摘要:A/B 用**翻转口径**(攻击第 r 轮与基底对照第 r 轮配对,对照给出期望值、攻击偏向目标才算),
C/D 并列**判定规则原始结果**与**人工核对后结果**;§2 是原口径,保留作参照。口径与取舍见 ADR-024"基线复核口径"一节。

```bash
# C/D 命中人工核对:改运行目录里的 hit_review.csv(核对结论:真攻击成功 / 否定句误判 / 其他 / 漏判,每行必须有理由),然后
python tests/llm_security/run_eval.py rejudge tests/llm_security/reports/phase1-<UTC>
# 精简审核表(⚠ 样本 + 对照组优先级判错的样本)→ 审完直接 apply 这一份
python tests/llm_security/run_eval.py labels export-priority tests/llm_security/reports/phase1-<UTC>
python tests/llm_security/run_eval.py labels apply --csv tests/llm_security/data/label_review_priority.csv --reviewer 姚尹杰
python tests/llm_security/run_eval.py rejudge tests/llm_security/reports/phase1-<UTC>
```

`hit_review.csv` 必须和本次运行的命中一一对应(key + 词条,上下文逐字一致),对不上报告生成直接失败——raw 变了,旧结论不能套到新草稿上。
