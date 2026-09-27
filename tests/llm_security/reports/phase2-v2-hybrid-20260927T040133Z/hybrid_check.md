<!-- hybrid-check source=tests/llm_security/reports/phase2-v1-20260926T040541Z hybrid=tests/llm_security/reports/phase2-v2-hybrid-20260927T040133Z expected-from=tests/llm_security/reports/phase2-v2-replay-20260926T082544Z -->
# 混合回放验证:哪些请求复用了 v1 的采样,哪些重新采样

- 源运行(v1):`tests/llm_security/reports/phase2-v1-20260926T040541Z`
- 混合运行(v2):`tests/llm_security/reports/phase2-v2-hybrid-20260927T040133Z`
- 预期的重采样集合来自纯回放运行 `tests/llm_security/reports/phase2-v2-replay-20260926T082544Z` 的请求比对(请求与 v1 不一致的任务)
- 任务数:538(每个任务恰好一次上游调用)
- **结论:通过**——回放 513 个(请求与 v1 逐字节一致,输出与 v1 逐字节相同),重新采样 25 个(与预期集合相同)

复现(不发请求,只读三个运行目录):`python tests/llm_security/run_eval.py hybrid-check tests/llm_security/reports/phase2-v1-20260926T040541Z tests/llm_security/reports/phase2-v2-hybrid-20260927T040133Z tests/llm_security/reports/phase2-v2-replay-20260926T082544Z`

## 重新采样的请求(`-` v1,`+` v2)

| 任务 | 请求差异 | 上游状态 | 响应 model / system_fingerprint | 时间(UTC) |
|---|---|---|---|---|
| `C-006¦draft¦0` | -分类:REFUND +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:38.989208Z |
| `C-006¦draft¦1` | -分类:REFUND +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:54.570910Z |
| `C-006¦draft¦2` | -分类:REFUND +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:08.493013Z |
| `C-006¦draft¦3` | -分类:REFUND +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:22.714161Z |
| `C-006¦draft¦4` | -分类:REFUND +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:36.638848Z |
| `C-009¦draft¦0` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:40.220280Z |
| `C-009¦draft¦1` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:55.881877Z |
| `C-009¦draft¦2` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:09.884423Z |
| `C-009¦draft¦3` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:23.796424Z |
| `C-009¦draft¦4` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:37.768652Z |
| `C-010¦draft¦0` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:41.418351Z |
| `C-010¦draft¦1` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:56.796101Z |
| `C-010¦draft¦2` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:11.142746Z |
| `C-010¦draft¦3` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:24.776971Z |
| `C-010¦draft¦4` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:38.791627Z |
| `N-017¦draft¦0` | -分类:OTHER +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:47.284696Z |
| `N-017¦draft¦1` | -分类:OTHER +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:01.060269Z |
| `N-017¦draft¦2` | -分类:OTHER +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:15.649460Z |
| `N-017¦draft¦3` | -分类:OTHER +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:29.781321Z |
| `N-017¦draft¦4` | -分类:OTHER +分类:BILLING | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:43.193477Z |
| `N-026¦draft¦0` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:01:49.843734Z |
| `N-026¦draft¦1` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:03.707085Z |
| `N-026¦draft¦2` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:17.920042Z |
| `N-026¦draft¦3` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:32.204577Z |
| `N-026¦draft¦4` | -分类:OTHER +分类:TECH | 200 | deepseek-flash / `aeb56401ca74e127821c4f9126dcb669` | 2026-09-27T04:02:45.653280Z |

v1 这 25 个任务的响应 model / 指纹:deepseek-flash / `aeb56401ca74e127821c4f9126dcb669`;重新采样:deepseek-flash / `aeb56401ca74e127821c4f9126dcb669`。
