#!/usr/bin/env bash
# 梯度压测:同一个脚本按并发梯度连跑几轮,每轮一个独立的 jtl。
# 用法: bash run_ladder.sh ticket_create.jmx "10 20 50" 60
#       bash run_ladder.sh grab_race.jmx "10 20 50 100"
# 依赖:jmeter 在 PATH 上(或设 JMETER_HOME);服务和基础设施已经起来。
set -euo pipefail
JMX="${1:?jmx 文件}"
LADDER="${2:-10 20 50}"
DURATION="${3:-60}"
JMETER="${JMETER_HOME:+$JMETER_HOME/bin/}jmeter"
STAMP=$(date +%Y%m%d-%H%M%S)
NAME=$(basename "$JMX" .jmx)
mkdir -p results
for T in $LADDER; do
  OUT="results/${NAME}-t${T}-${STAMP}.jtl"
  echo "=== $NAME threads=$T duration=${DURATION}s -> $OUT"
  "$JMETER" -n -t "$JMX" \
    -Jthreads="$T" -Jduration="$DURATION" -Jrampup="$(( T / 5 > 0 ? T / 5 : 1 ))" \
    -JresultsFile="$OUT" \
    -l "results/${NAME}-t${T}-${STAMP}-summary.jtl" \
    -j "results/${NAME}-t${T}-${STAMP}.log"
done
echo "结果在 results/,用 jmeter -g <jtl> -o <dir> 出 HTML 报告"
