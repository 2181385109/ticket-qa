# Arthas 手册(本项目 2026-09-20 压测阶段实际用过的命令)

> 每条命令都在这台机器上对 pid 15936 跑过,输出在 `tests/perf/results/arthas_*.txt`。
> 格式:命令原样 → 它干什么 → 什么场景用 → 这次用它得到了什么 / 踩了什么坑。
> 版本:Arthas 4.3.5(`arthas-boot.jar` 的位置由 `ARTHAS_BOOT` 指定,本体首次运行时从 aliyun 下到 `~/.arthas/lib`),JDK 17。

## 0. 附加与批处理

```bash
java -jar arthas-boot.jar --attach-only <pid>        # 只把 agent 挂进目标 JVM,不进交互 shell
java -jar arthas-boot.jar <pid> -c "cmd1; cmd2"       # 批处理:执行完退出。tests/perf/tools/arthas.sh 就是它的封装(去 banner、可落盘)
java -jar arthas-boot.jar <pid>                       # 交互 shell(手工排障时用)
```
- 场景:压测里要"发流量的同时采样",所以全部用批处理 + 后台执行:先起 `watch`/`trace`(它们会阻塞到 `-n` 次命中),再发流量。
- 坑 1:**批处理客户端偶发起不来**(本次 10 次里 3 次输出只有 banner、没有 `Affect` 行),尤其是两个客户端几乎同时启动、或上一个客户端刚退出时。对策:起一个 → 循环等到文件里出现 `Affect(class count: …)` 再发流量;需要多个观测点时**合成一个 `watch -E`** 而不是起多个客户端。
- 坑 2:客户端被 kill 掉,已增强的类不会自动还原;两个客户端 `tee` 到同一个文件会交错。每轮采证后 `reset`,文件名带轮次 tag。
- 坑 3:目标 JVM 的 `Picked up JAVA_TOOL_OPTIONS:` 提示是无害的。

## 1. 看现场:dashboard / thread / memory / jvm

```bash
dashboard -n 1                    # 一屏:线程 CPU 排行、堆各区、GC 次数/耗时、运行时信息;-n 1 只刷一次就退出(批处理必须加)
thread -b                         # 找"最阻塞"的线程——持有锁让别人 BLOCKED 的那个。本次输出 "No most blocking thread found!"
thread --state BLOCKED            # 列出 BLOCKED 状态的线程。本次 0 个
thread --state RUNNABLE           # 列出 RUNNABLE 线程(在等 socket 的线程也是 RUNNABLE,JVM 不知道它在等 MySQL)
thread <id>                       # 单个线程的栈
thread -n 5                       # CPU 最忙的 5 个线程及栈(本次没用到,等锁的线程不吃 CPU)
memory                            # 堆 / 各代 / 非堆 / codeheap 用量。本次 heap 234M/1024M,老年代 27M——排除内存压力
jvm                               # 启动参数、类加载、线程计数(COUNT/PEAK/DEADLOCK)、GC 收集器。本次 DEADLOCK-COUNT 0,PEAK 191 线程
```
- 场景:先看"线程在等什么"再决定往哪查。`thread -b` + `--state BLOCKED` 是排除 JVM 锁竞争的两句;排除后再去看 MySQL 侧的锁。
- 得到的结论:抢单竞争时 5 个线程全部 RUNNABLE,栈停在 `NioSocketImpl.read ← ClientPreparedStatement.execute ← TicketService.grab:224`——等的是 MySQL 行锁,不是 Java 锁。
- 配套:`thread` 看栈不够直观时用 JDK 自带的 `jcmd <pid> Thread.print > dump.txt`(`results/jcmd_threadprint_lockhold.txt`),全量栈更适合 grep。

## 2. 不改代码读运行时对象:vmtool + OGNL

```bash
# 连接池此刻真实状态(比指标端点更即时,也能拿到指标没暴露的字段)
vmtool --action getInstances --className com.zaxxer.hikari.pool.HikariPool --express '#p=instances[0], "total/idle/active/awaiting="+#p.getTotalConnections()+"/"+#p.getIdleConnections()+"/"+#p.getActiveConnections()+"/"+#p.getThreadsAwaitingConnection()'
# 连接池配置
vmtool --action getInstances --className com.zaxxer.hikari.HikariDataSource --express '#d=instances[0], "maxPoolSize/minIdle/connectionTimeout/idleTimeout="+#d.getMaximumPoolSize()+"/"+#d.getMinimumIdle()+"/"+#d.getConnectionTimeout()+"/"+#d.getIdleTimeout()'
# Tomcat 线程池(本项目没暴露 tomcat_threads_* 指标,只能这样读)
vmtool --action getInstances --className org.apache.tomcat.util.net.NioEndpoint --express '#e=instances[0], "maxThreads/minSpare/currentThreads/busy/maxConnections/acceptCount="+#e.getMaxThreads()+"/"+#e.getMinSpareThreads()+"/"+#e.getCurrentThreadCount()+"/"+#e.getCurrentThreadsBusy()+"/"+#e.getMaxConnections()+"/"+#e.getAcceptCount()'
# 调一个方法(有副作用!):把池里连接软驱逐,让新连接带上 MySQL 新的会话变量(long_query_time=0)
vmtool --action getInstances --className com.zaxxer.hikari.HikariDataSource --express 'instances[0].getHikariPoolMXBean().softEvictConnections()'
```
- 场景:想知道"此刻池里有几条""Tomcat 线程池到底配了多少"而不想改配置暴露指标;或者需要对运行中的对象做一个操作(驱逐连接、清缓存)。
- OGNL 要点:`instances` 是数组;`#p=instances[0], expr` 先赋变量再算;字符串拼接用 `+`;不要写 `instances[0].{a(), b()}`——那是集合投影,只会得到最后一个元素(第一次就踩了)。
- 得到的结论:成功数 = 池内连接数 + 1 的规律,全靠每轮前这一条读出的 total/idle。

## 3. 调用链耗时:trace

```bash
# Spring 事务代理三段:拿连接(createTransactionIfNecessary)/ 业务体 / 提交(含 AFTER_COMMIT 里的 MQ 发送)
trace org.springframework.transaction.interceptor.TransactionAspectSupport invokeWithinTransaction 'params[0].name=="grab"' -n 3
# 业务方法内部各行耗时;--skipJDKMethod false 连 JDK 方法(LocalDateTime.now 等)也列出来
trace com.ticketqa.ticket.TicketService grab -n 3 --skipJDKMethod false
# Controller 层:一个请求在 Service 之外还花了多少
trace com.ticketqa.ticket.TicketController grab -n 8
```
- 场景:一个方法慢,想知道慢在哪一行调用。第三个参数是 OGNL 条件,`params[0].name=="grab"` 把事务代理里所有 `@Transactional` 方法过滤到只剩 grab。
- 得到的结论:无竞争一次 grab 事务 13~27 ms = 拿连接 1 ms + 业务 6~16 ms(其中 SELECT 5 ms、UPDATE 2~4.5 ms、审计 1.8 ms)+ 提交 5~8 ms;稳态 50 线程时 Controller 107~119 ms,99.9% 在 `TicketService.grab()`。
- 坑:**压测进行中再附加 `trace`,前几次命中是残缺的树**(类被增强时那些调用已经在飞,只记到后半段),`results/arthas_trace_tx_grab_t50_steady2.txt` 就是。要么压测前附加、用 `-n` 大一点让它跨过 ramp-up,要么改用 `watch`。
- 另一个坑:用 `@java.lang.System@currentTimeMillis() > 1789904155000L` 这类时间条件想跳过 ramp-up 没生效(命中仍在压测开始 4 s 内),没细查原因;改成"压测 14 s 后再附加"解决。

## 4. 逐次调用取值 + 时间戳:watch

```bash
# JDBC 层一网打尽:拿连接 / 每条 SQL 的执行 / commit / rollback,返回 [epoch ms, 线程名, 耗时, 方法名, SQL 文本]
watch -E com.zaxxer.hikari.pool.(ProxyPreparedStatement|ProxyConnection|HikariPool) (execute|commit|rollback|getConnection) '#s=(target instanceof com.zaxxer.hikari.pool.HikariPool) ? "getConnection" : target.delegate.toString(), {@java.lang.System@currentTimeMillis(), @java.lang.Thread@currentThread().getName(), #cost, method.name, (#s.length()>520 ? #s.substring(0,520) : #s)}' '@java.lang.Thread@currentThread().getName().startsWith("http")' -n 260 -x 1
# 只看拿连接等了多久(params.length==1 选中带 timeout 参数的私有重载,避免重复计数)
watch com.zaxxer.hikari.pool.HikariPool getConnection '{@java.lang.System@currentTimeMillis(), @java.lang.Thread@currentThread().getName(), #cost}' 'params.length==1 && @java.lang.Thread@currentThread().getName().startsWith("http")' -n 40 -x 1
# 事务代理三段的稳态分布(240 个样本,按方法名和 params 里的 Method 名分组)
watch -E org.springframework.transaction.interceptor.TransactionAspectSupport (invokeWithinTransaction|createTransactionIfNecessary|commitTransactionAfterReturning) '{method.name, #cost, (params[0] instanceof java.lang.reflect.Method ? params[0].name : (params.length>2 ? params[2].toString() : ""))}' '@java.lang.Thread@currentThread().getName().startsWith("http")' -n 240 -x 1
```
- 场景:要的不是"平均多慢",而是"每一次调用发生在哪个毫秒、哪个线程",用来和别的时间源(JMeter 采样、MySQL slow log、审计表)对齐。`-x 1` 控制结果展开深度;`#cost` 是本次调用耗时;表达式默认在**返回时**求值,所以"发出时刻 = 时间戳 − #cost"。
- `-E` 让类名和方法名都按正则匹配,一个 watcher 覆盖多个类——比起多个客户端可靠得多。
- 得到的结论:窗口宽度(SELECT 发出 → COMMIT 返回)无竞争 12.3 / 13.1 ms、20 线程 28.8 ms;409 线程在 `getConnection` 里等了 63~88 ms;稳态 50 线程拿连接 p50 75.7 ms。
- 坑 1:**过滤线程名**。不加 `startsWith("http")` 时 SLA 调度线程 `scheduling-1` 每 30 s 一轮扫描,几十条 SQL 把 `-n` 额度吃光(第一次 150 条里 130 条是它的)。
- 坑 2:Hikari 生成的 `HikariProxyPreparedStatement` 和父类 `ProxyPreparedStatement` 都被增强,**同一次调用出两条**(内层 cost 略小)。`tools/parse_watch.py` 按线程 + 类型 + 返回时刻去重,保留外层。`getConnection()` 和 `getConnection(long)` 同理。
- 坑 3:`target.delegate.toString()` 对 MySQL 的 `ClientPreparedStatement` 会给出参数已代入的完整 SQL——很有用,但 UPDATE 语句四五百字符,`substring` 截短时别把 `WHERE id=…` 截掉(第一次截 110 就把 SELECT 的 WHERE 截没了,过滤全失效)。
- 坑 4:`method.name` 是 Arthas 提供的变量;`params`、`target`、`returnObj`、`throwExp`、`#cost` 也是。

## 5. 还原与收尾

```bash
reset                             # 还原所有被 watch/trace 增强的类。每轮采证结束必做,否则增强逻辑一直在跑、下一轮的数字带着观测开销
stop                              # 卸载 agent(本次没用,agent 一直挂着不影响)
```

## 6. 和 Arthas 配合的非 Arthas 命令(同样是这次的取证链)

```bash
# JDK
jcmd <pid> Thread.print > dump.txt                     # 全量线程栈;grep "TicketService.grab" 数有几个线程卡在哪一行
# JVM 启动参数(本次服务这样起,GC 日志可回放)
java -Xms1g -Xmx1g -XX:+UseG1GC -Xlog:gc*:file=logs/gc-<ts>.log:time,uptime,level,tags -jar app.jar
# MySQL:把每条语句的 µs 级 start/query/lock time 记到表里(会拖慢;用完关)
SET GLOBAL slow_query_log=ON; SET GLOBAL long_query_time=0; SET GLOBAL log_output='TABLE'; TRUNCATE mysql.slow_log;
SELECT start_time, query_time, lock_time, LEFT(sql_text,60) FROM mysql.slow_log WHERE sql_text LIKE 'UPDATE ticket%WHERE id=8240%' ORDER BY start_time;
#   注意:long_query_time 是会话变量,服务已有的池化连接不会变——要么等它们过期,要么 vmtool softEvictConnections
#   注意:slow_log 表的 start_time 实际是语句结束时刻(用 query_time 反推能对上),别当成开始时刻
SET GLOBAL slow_query_log=OFF; SET GLOBAL long_query_time=10; SET GLOBAL log_output='FILE';
# MySQL:执行计划与锁统计
EXPLAIN <SQL>\G
SELECT COUNT_STAR, SUM_TIMER_WAIT/1e12 total_s, SUM_LOCK_TIME/1e12 lock_s, LEFT(DIGEST_TEXT,70) FROM performance_schema.events_statements_summary_by_digest WHERE SCHEMA_NAME='ticket_qa' ORDER BY SUM_LOCK_TIME DESC;
SELECT * FROM performance_schema.data_lock_waits;      # 只在等待发生的那一刻有行;持锁演示时有用
SHOW VARIABLES WHERE Variable_name IN ('innodb_lock_wait_timeout','transaction_isolation','innodb_flush_log_at_trx_commit','sync_binlog');
# MySQL:压测中每秒看谁在忙(tools/mysql_probe.py 就是循环这两句)
SELECT STATE, COUNT(*) FROM information_schema.PROCESSLIST WHERE USER='ticketqa' AND COMMAND<>'Sleep' GROUP BY 1;
SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME IN ('Innodb_os_log_fsyncs','Questions','Threads_running');
# 人为制造并长时间持有行锁(把 ~30 ms 的窗口拉到 45 s,让 thread / jcmd / processlist 都来得及看)
BEGIN; UPDATE ticket SET assignee_id=2, status='ASSIGNED' WHERE id=?; SELECT SLEEP(45); COMMIT;
# WireMock:全局延迟,注入 LLM 超时(不用改桩)
curl -X POST localhost:8089/__admin/settings -H 'Content-Type: application/json' -d '{"fixedDelay": 5000}'
curl -X POST localhost:8089/__admin/settings -H 'Content-Type: application/json' -d '{"fixedDelay": 0}'
# 指标端点里最有用的几个名字
hikaricp_connections{,_idle,_active,_pending,_acquire_seconds_max,_timeout_total}  jvm_gc_pause_seconds_{count,sum,max}  jvm_threads_states_threads
```

## 7. 这次的取证顺序(可照抄)

1. `vmtool` 读池状态 → 记进环境快照(`tools/env_state.py` 已经自动做,但它读的是指标端点;vmtool 是校验)。
2. `watch -E … (execute|commit|rollback|getConnection)` 后台起好,等 `Affect`。
3. 发流量(`grab_round.sh` / `run_load.sh`)。
4. `tools/parse_watch.py` 把 watch 输出变成按线程的时间线;和 `tools/race_timeline.py`(服务日志)、`mysql.slow_log`、审计表对齐。
5. `thread -b` / `--state BLOCKED` / `jcmd Thread.print` 排除 JVM 锁;`EXPLAIN` + digest 排除索引;GC 日志按时间戳排除 GC。
6. `reset`。
