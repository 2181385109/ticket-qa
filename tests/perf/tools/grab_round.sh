#!/usr/bin/env bash
# 跑一轮抢单竞态并立刻取证:jmeter grab_race.jmx -Jthreads=N → 从 jmeter 日志拿到目标工单 id
# → HTTP 层结果分布(jtl 标签)→ 数据库取证(grab_evidence.py)。
# 用法(在 tests/perf 下):bash tools/grab_round.sh <threads> [tag]
#   tag 用来区分同并发的多次重复,默认 r1。结果:results/grab_t<N>_<tag>{.jtl,_raw.jtl,.log,_evidence.txt}
set -euo pipefail
T="${1:?threads}"
TAG="${2:-r1}"
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"   # 机器相关路径(见 local.env.example)
JAVA="${JAVA_HOME:+$JAVA_HOME/bin/}java"
JMETER_JAR="${JMETER_JAR:-${JMETER_HOME:?设置 JMETER_HOME(JMeter 安装目录)或 JMETER_JAR}/bin/ApacheJMeter.jar}"
PY="${PY:-python}"
NAME="grab_t${T}_${TAG}"
mkdir -p results
echo "=== $(date +%T) grab_race threads=$T tag=$TAG"
"$JAVA" -Xms512m -Xmx512m -jar "$JMETER_JAR" -n -t grab_race.jmx -Jthreads="$T" \
  -JresultsFile="results/${NAME}_raw.jtl" -l "results/${NAME}.jtl" -j "results/${NAME}.log" 2>&1 \
  | grep -E "^summary =|end of run" | tail -2
TICKET=$(grep -a -o "grab_race .* id=[0-9]*" "results/${NAME}.log" | tail -1 | grep -o "[0-9]*$" || true)
echo "ticket_id=$TICKET"
echo "--- HTTP 层结果分布(jtl 标签)"
"$PY" tools/jtl_stats.py "results/${NAME}.jtl" --label grab --labels 2>/dev/null
echo "--- 数据库取证"
"$PY" tools/grab_evidence.py "$TICKET" 2>/dev/null | tee "results/${NAME}_evidence.txt"
