#!/usr/bin/env bash
# 拐点压测完整梯度,和 2026-09-20 修复前那轮完全相同的顺序与参数,便于逐档对比:
#   清库 → 创建链路 10/20/50/100/200 线程各 60 s → 导出 id 池 → 抢单链路 10/20/50 线程 20 s、100/200 线程 60 s
#   (每轮抢单前 reset_grabbed + export_ids,和当时一样;SLA 调度器在后台照常跑,轮前积压记录在 env_before 里)
# 用法(在 tests/perf 下):bash tools/ladder_full.sh <前缀>       产物 results/<前缀>_{create,grab}_t<N>_report.md
set -uo pipefail
PREFIX="${1:?prefix}"
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"   # 机器相关路径(见 local.env.example)
PY="${PY:-python}"
export PYTHONIOENCODING=utf-8
mkdir -p results
LOG="results/${PREFIX}_ladder.log"
exec > >(tee -a "$LOG") 2>&1

echo "=== $(date '+%F %T') 清库(与修复前 step4 相同:五张业务表 TRUNCATE,坐席保留)"
"$PY" - <<'EOF'
import pymysql
c = pymysql.connect(host='127.0.0.1', user='ticketqa', password='ticketqa123', database='ticket_qa', autocommit=True)
cur = c.cursor()
cur.execute("SELECT (SELECT COUNT(*) FROM ticket), (SELECT COUNT(*) FROM ticket_audit_log), (SELECT COUNT(*) FROM mq_message_dedup)")
print("before:", cur.fetchone())
for t in ("ticket_attachment", "ticket_audit_log", "llm_call_log", "mq_message_dedup", "ticket"):
    cur.execute(f"TRUNCATE TABLE {t}")
cur.execute("SELECT (SELECT COUNT(*) FROM ticket), (SELECT COUNT(*) FROM agent)")
print("after (tickets, agents):", cur.fetchone())
EOF
sleep 5

for T in 10 20 50 100 200; do
  echo "=== $(date '+%F %T') create t=$T"
  bash tools/run_load.sh ticket_create.jmx "$T" "${PREFIX}_create_t${T}" 60
done

for T in 10 20 50 100 200; do
  echo "=== $(date '+%F %T') grab t=$T 前置:重置上一轮 + 重导 id 池"
  "$PY" tools/reset_grabbed.py
  "$PY" tools/export_ids.py
  D=20; [ "$T" -ge 100 ] && D=60
  bash tools/run_load.sh grab_throughput.jmx "$T" "${PREFIX}_grab_t${T}" "$D" "-JidsCsv=results/ticket_ids.csv"
done

echo "=== $(date '+%F %T') 汇总"
for f in results/${PREFIX}_create_t*.jtl results/${PREFIX}_grab_t*.jtl; do
  case "$f" in *_raw.jtl) continue;; esac
  printf "%s  " "$(basename "$f" .jtl)"; "$PY" tools/jtl_stats.py "$f" 2>/dev/null | tail -1
done
echo "=== $(date '+%F %T') 完成"
