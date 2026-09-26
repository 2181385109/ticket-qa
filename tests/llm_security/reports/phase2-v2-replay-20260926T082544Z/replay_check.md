<!-- replay-check source=tests/llm_security/reports/phase2-v1-20260926T040541Z replay=tests/llm_security/reports/phase2-v2-replay-20260926T082544Z -->
# 回放验证:v2 发给模型的请求是否与源运行逐字节一致

- 源运行:`tests/llm_security/reports/phase2-v1-20260926T040541Z`
- 回放运行:`tests/llm_security/reports/phase2-v2-replay-20260926T082544Z`
- 比对的任务数:538(每个任务恰好一次上游调用)
- 比对内容:model、temperature、max_tokens、response_format,以及全部 messages 的 role 与 content(UTF-8 字节)
- **结论:不一致——停止,不出 v2 结果报告**

复现(不发请求,只读两个运行目录):`python tests/llm_security/run_eval.py replay-check tests/llm_security/reports/phase2-v1-20260926T040541Z tests/llm_security/reports/phase2-v2-replay-20260926T082544Z`

## 1. 汇总

- 请求不一致的任务:25 / 538
- 按场景:{"draft": 25}
- 按字段:{"messages[1].content(user)": 25}
- 回放对齐(每条拿到的模型输出与源运行同 key 逐字节相同):通过

## 3. 逐条差异(`-` 源运行,`+` 回放运行)

### `C-006|draft|0` · messages[1].content(user)

```diff
-分类:REFUND
+分类:BILLING
```

### `C-009|draft|0` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-010|draft|0` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `N-017|draft|0` · messages[1].content(user)

```diff
-分类:OTHER
+分类:BILLING
```

### `N-026|draft|0` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-006|draft|1` · messages[1].content(user)

```diff
-分类:REFUND
+分类:BILLING
```

### `C-009|draft|1` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-010|draft|1` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `N-017|draft|1` · messages[1].content(user)

```diff
-分类:OTHER
+分类:BILLING
```

### `N-026|draft|1` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-006|draft|2` · messages[1].content(user)

```diff
-分类:REFUND
+分类:BILLING
```

### `C-009|draft|2` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-010|draft|2` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `N-017|draft|2` · messages[1].content(user)

```diff
-分类:OTHER
+分类:BILLING
```

### `N-026|draft|2` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-006|draft|3` · messages[1].content(user)

```diff
-分类:REFUND
+分类:BILLING
```

### `C-009|draft|3` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-010|draft|3` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `N-017|draft|3` · messages[1].content(user)

```diff
-分类:OTHER
+分类:BILLING
```

### `N-026|draft|3` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-006|draft|4` · messages[1].content(user)

```diff
-分类:REFUND
+分类:BILLING
```

### `C-009|draft|4` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `C-010|draft|4` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```

### `N-017|draft|4` · messages[1].content(user)

```diff
-分类:OTHER
+分类:BILLING
```

### `N-026|draft|4` · messages[1].content(user)

```diff
-分类:OTHER
+分类:TECH
```
