#!/usr/bin/env bash
# 抢单竞态修复后的回归:用和压测定位时完全相同的手段重跑(grab_race.jmx 集合点 → grab_evidence.py 查库),
# 每轮记录 HTTP 层 200/409 分布、审计 to_status='ASSIGNED' 行数、审计序列连续性、以及三层防线的指标增量。
#
# 用法(在 tests/perf 下):bash tools/regress_grab.sh [前缀]        默认前缀 fix
#   轮次固定为压测时的复现档位:2 线程 × 5 轮、20 线程、100 线程;结果汇总到 results/<前缀>_regress_summary.md
#   额外一轮 "20 线程 + Redis 停机" 需要手动 docker compose stop redis 后单独跑:
#   bash tools/grab_round.sh 20 fix_noredis && python tools/grab_evidence.py --latest
set -uo pipefail
PREFIX="${1:-fix}"
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"   # 机器相关路径(见 local.env.example)
PY="${PY:-python}"
export PYTHONIOENCODING=utf-8
mkdir -p results
SUMMARY="results/${PREFIX}_regress_summary.md"
METRICS_URL="${BASE_URL:-http://localhost:8080}/actuator/prometheus"

metric() { curl -s "$METRICS_URL" | grep "^$1{" | awk '{s+=$2} END{printf "%d", s}'; }
hikari() { curl -s "$METRICS_URL" | grep -E "^hikaricp_connections(_idle|_active)?\{" | awk -F'[ }]' '{n=$1; sub(/\{.*/,"",n); printf "%s=%s ", n, $NF}'; }

{
  echo "# 抢单竞态回归(${PREFIX})$(date '+%F %T')"
  echo
  echo "服务 $(curl -s localhost:8080/actuator/health | head -c 40) / 修复代码 git $(git rev-parse --short HEAD 2>/dev/null)"
  echo
  echo "| 轮次 | 线程 | 压测前池 | HTTP 200 | HTTP 409 | 其他 | 审计 ASSIGNED 行数 | 审计序列连续 | Δlock_acquired | Δlock_rejected | Δlock_unavailable | Δdb_conflict | Δversion_conflict | 工单 id |"
  echo "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
} > "$SUMMARY"

run_round() {
  local T="$1" TAG="$2"
  local a0 r0 u0 c0 v0 pool
  a0=$(metric grab_lock_acquired_total); r0=$(metric grab_lock_rejected_total); u0=$(metric grab_lock_unavailable_total)
  c0=$(metric grab_conflict_total); v0=$(metric ticket_version_conflict_total); pool=$(hikari)
  bash tools/grab_round.sh "$T" "$TAG" > "results/grab_t${T}_${TAG}.round.txt" 2>&1
  local ev="results/grab_t${T}_${TAG}_evidence.txt"
  local ticket n_assigned chain codes c200 c409 cother
  ticket=$(grep -o "ticket_id=[0-9]*" "results/grab_t${T}_${TAG}.round.txt" | head -1 | cut -d= -f2)
  n_assigned=$(grep -o "行数 = [0-9]*" "$ev" | head -1 | grep -o "[0-9]*$")
  chain=$(grep -o "连续.*= \(YES\|NO.*\)" "$ev" | sed 's/.*= //')
  c200=$(awk -F, 'NR>1 && $1 ~ /^[0-9]+$/ && $3 ~ /^grab/ && $4=="200"{n++} END{print n+0}' "results/grab_t${T}_${TAG}.jtl")
  c409=$(awk -F, 'NR>1 && $1 ~ /^[0-9]+$/ && $3 ~ /^grab/ && $4=="409"{n++} END{print n+0}' "results/grab_t${T}_${TAG}.jtl")
  cother=$(awk -F, 'NR>1 && $1 ~ /^[0-9]+$/ && $3 ~ /^grab/ && $4!="200" && $4!="409"{n++} END{print n+0}' "results/grab_t${T}_${TAG}.jtl")
  local a1 r1 u1 c1 v1
  a1=$(metric grab_lock_acquired_total); r1=$(metric grab_lock_rejected_total); u1=$(metric grab_lock_unavailable_total)
  c1=$(metric grab_conflict_total); v1=$(metric ticket_version_conflict_total)
  echo "| ${TAG} | ${T} | ${pool} | ${c200} | ${c409} | ${cother} | ${n_assigned} | ${chain} | $((a1-a0)) | $((r1-r0)) | $((u1-u0)) | $((c1-c0)) | $((v1-v0)) | ${ticket} |" >> "$SUMMARY"
  echo "=== t=${T} ${TAG}: 200=${c200} 409=${c409} other=${cother} audit_assigned=${n_assigned} chain=${chain} ticket=${ticket}"
}

for r in 1 2 3 4 5; do run_round 2 "${PREFIX}_r${r}"; done
run_round 20 "${PREFIX}_r1"
run_round 100 "${PREFIX}_r1"

echo >> "$SUMMARY"
echo "全库扫描(to_status='ASSIGNED' 多于 1 行的工单):" >> "$SUMMARY"
echo '```' >> "$SUMMARY"
"$PY" tools/grab_evidence.py --scan >> "$SUMMARY" 2>/dev/null
echo '```' >> "$SUMMARY"
echo "汇总: $SUMMARY"
cat "$SUMMARY"
