"""MySQL 侧探针:压测前后各抓一次 fsync 计数与文件等待,压测中每秒抓一次 processlist 状态分布。
用法:python tools/mysql_probe.py <秒数> <输出文件>
"""
import pymysql, sys, time, collections
c = pymysql.connect(host='127.0.0.1', user='root', password='root123', database='ticket_qa', autocommit=True)
cur = c.cursor()
def status():
    cur.execute("SELECT VARIABLE_NAME, VARIABLE_VALUE FROM performance_schema.global_status WHERE VARIABLE_NAME IN ('Innodb_os_log_fsyncs','Innodb_data_fsyncs','Com_commit','Com_rollback','Innodb_row_lock_waits','Innodb_row_lock_time','Threads_running','Threads_connected','Questions')")
    return {k: int(v) for k, v in cur.fetchall()}
def waits():
    cur.execute("SELECT EVENT_NAME, COUNT_STAR, SUM_TIMER_WAIT FROM performance_schema.events_waits_summary_global_by_event_name WHERE EVENT_NAME IN ('wait/io/file/innodb/innodb_log_file','wait/io/file/sql/binlog','wait/io/file/innodb/innodb_data_file','wait/synch/mutex/innodb/log_sys_mutex','wait/synch/mutex/sql/LOCK_commit')")
    return {n: (int(cnt), int(t)) for n, cnt, t in cur.fetchall()}
dur = float(sys.argv[1]); out = open(sys.argv[2], 'w', encoding='utf-8')
s0, w0, t0 = status(), waits(), time.time()
states = collections.Counter(); samples = 0; running = []
while time.time() - t0 < dur:
    cur.execute("SELECT COALESCE(STATE,'(none)'), COUNT(*) FROM information_schema.PROCESSLIST WHERE USER='ticketqa' AND COMMAND<>'Sleep' GROUP BY 1")
    rows = cur.fetchall(); samples += 1
    for st, n in rows: states[st] += n
    running.append(sum(n for _, n in rows))
    time.sleep(1)
s1, w1 = status(), waits()
el = time.time() - t0
print(f"探针时长 {el:.0f}s,processlist 采样 {samples} 次,ticketqa 非 Sleep 连接数 avg={sum(running)/len(running):.1f} max={max(running)}", file=out)
print("processlist 状态累计(次数 / 采样次数 = 平均同时处于该状态的连接数):", file=out)
for st, n in states.most_common(): print(f"  {n/samples:6.2f}  {st}", file=out)
print("global_status 差分:", file=out)
for k in s0: print(f"  {k:24s} +{s1[k]-s0[k]:8d}   ({(s1[k]-s0[k])/el:8.1f}/s)", file=out)
print("文件 / 互斥等待差分(次数, 总等待 ms, 平均 µs):", file=out)
for k in w0:
    dc = w1[k][0]-w0[k][0]; dt = (w1[k][1]-w0[k][1])/1e9
    print(f"  {k:45s} {dc:8d}  {dt:9.1f} ms  {dt*1000/dc if dc else 0:7.1f} µs", file=out)
out.close(); print(open(sys.argv[2], encoding='utf-8').read())
