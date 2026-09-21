# 2026-09-20 压测与故障注入的原始证据(节选)

从本机 `tests/perf/results/`(gitignore)复制的、findings 里引用到的文件。命名和 `tests/perf/tools/` 的产物一致:

| 前缀 | 来自 | 内容 |
|---|---|---|
| `grab_t<N>_<tag>_evidence.txt` | `tools/grab_evidence.py` | 一轮 grab_race 后的三条取证 SQL 与输出 |
| `grab_t*_timeline.txt` | `tools/race_timeline.py` | 从服务日志还原的逐线程 SELECT/UPDATE 毫秒时序 |
| `grab_t*_jdbc_timeline.txt` | `tools/parse_watch.py` | Arthas watch(JDBC 层)整理成的逐线程时间线 |
| `arthas_*.txt` | `tools/arthas.sh` | Arthas 原始输出(trace / watch / vmtool / thread / memory / jvm) |
| `hikari_before_*.txt` | vmtool | 每轮竞态压测前的池状态 |
| `mysql_*.txt`、`lockhold_*` | MySQL | slow log、EXPLAIN、digest、持锁演示 |
| `grab_t50_mysql_probe.txt` | `tools/mysql_probe.py` | 稳态 processlist / fsync / 文件等待 |
| `*_report.md` | `tools/run_load.sh` | 拐点压测每轮的完整报告(头部是压测前后的环境状态) |
| `step4_*`、`step5_*` | `tools/env_state.py` | 清库记录与基线快照、梯度汇总表 |
| `fault_*.log` | `tools/fault_probe.py` | 故障注入四个场景的探针日志 |
| `gc-20260920-175426.log` | JVM `-Xlog:gc*` | 全程 GC 日志 |
| `jcmd_threadprint_lockhold_grab_threads.txt` | `jcmd Thread.print` | 持锁期间 5 个 grab 线程的栈(全量 dump 190 KB 未入库) |

jtl / JMeter 日志 / 每秒指标 csv / docker stats 只在本机。
