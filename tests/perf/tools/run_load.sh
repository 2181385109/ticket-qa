#!/usr/bin/env bash
# 一轮压测 = 环境状态(前)→ 指标采样 + 容器 CPU 采样 → JMeter → 环境状态(后)→ 汇总成一份报告。
# 没有环境状态头的压测数字不可复现(HikariCP 池大小随时间收缩,同一并发得到不同结果),所以这里强制一起落盘。
#
# 用法(在 tests/perf 下):
#   bash tools/run_load.sh ticket_create.jmx 50 create_t50 60            # 50 线程 60 秒
#   bash tools/run_load.sh grab_throughput.jmx 50 grab_t50 30 "-JidsCsv=results/ticket_ids.csv"
# 产物(results/<tag>_*):env_before.md / env_after.md(+json)、metrics.csv、docker_stats.txt、
#   .jtl(-l 汇总)、_raw.jtl、.log、report.md(头部就是两份环境状态)
set -uo pipefail
JMX="${1:?jmx}"; T="${2:?threads}"; TAG="${3:?tag}"; DURATION="${4:-60}"; EXTRA="${5:-}"
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"   # 机器相关路径(见 local.env.example)
JAVA="${JAVA_HOME:+$JAVA_HOME/bin/}java"
JMETER_JAR="${JMETER_JAR:-${JMETER_HOME:?设置 JMETER_HOME(JMeter 安装目录)或 JMETER_JAR}/bin/ApacheJMeter.jar}"
PY="${PY:-python}"
export PYTHONIOENCODING=utf-8   # MSYS_NO_PATHCONV 只给 wsl.exe 那一行用,否则 java.exe 收到 /d/... 路径打不开 jar
RAMP=$(( T / 5 > 0 ? T / 5 : 1 ))
mkdir -p results
R="results/${TAG}"
HERE_WSL="/mnt/$(pwd | sed 's|^/\([a-z]\)/|\1/|')"
echo "=== $(date +%T) $JMX threads=$T rampup=${RAMP}s duration=${DURATION}s tag=$TAG"

"$PY" tools/env_state.py --label "${TAG} 之前" --out "${R}_env_before.md" > /dev/null 2>&1
( "$PY" tools/metrics_sampler.py --out "${R}_metrics.csv" --duration $(( DURATION + RAMP + 15 )) --interval 1 > /dev/null 2>&1 & )
( MSYS_NO_PATHCONV=1 wsl.exe -d Ubuntu-24.04 -u root -- bash "${HERE_WSL}/tools/docker_stats_loop.sh" $(( DURATION + RAMP + 10 )) "${HERE_WSL}/${R}_docker_stats.txt" > /dev/null 2>&1 & )
sleep 2
"$JAVA" -Xms1g -Xmx1g -jar "$JMETER_JAR" -n -t "$JMX" -Jthreads="$T" -Jrampup="$RAMP" -Jduration="$DURATION" $EXTRA \
  -JresultsFile="${R}_raw.jtl" -l "${R}.jtl" -j "${R}.log" 2>&1 | grep -E "^summary =|end of run" | tail -2
sleep 12
"$PY" tools/env_state.py --label "${TAG} 之后" --out "${R}_env_after.md" > /dev/null 2>&1

{
  echo "# 压测轮次 ${TAG}"
  echo
  echo "脚本 \`$JMX\`,线程 $T,ramp-up ${RAMP}s,持续 ${DURATION}s,额外参数 \`${EXTRA}\`,执行时间 $(date '+%F %T')"
  echo "JMeter 与被测服务同机(Ryzen 7 7840H 8C16T / 16 GB);MySQL/Redis/RabbitMQ/WireMock 在 WSL2 Docker(4 vCPU)"
  echo
  echo "## 环境状态(压测前)"; echo; cat "${R}_env_before.md"; echo
  echo "## 环境状态(压测后)"; echo; cat "${R}_env_after.md"; echo
  echo "## JMeter 结果"; echo; echo '```'; "$PY" tools/jtl_stats.py "${R}.jtl" --labels 2>/dev/null; echo '```'; echo
  echo "## 服务侧指标(每秒采样,峰值 / 均值 / 差分)"; echo; echo '```'; "$PY" tools/metrics_sampler.py --summarize "${R}_metrics.csv" 2>/dev/null; echo '```'; echo
  echo "## 容器 CPU(docker stats,每 ~4 s 一次)"; echo; echo '```'
  awk '{split($3,a,"="); gsub("%","",a[2]); n[$2]++; s[$2]+=a[2]; if(a[2]>m[$2])m[$2]=a[2]} END{for(k in n) printf "%-22s samples=%d avg_cpu=%.1f%% max_cpu=%.1f%%\n",k,n[k],s[k]/n[k],m[k]}' "${R}_docker_stats.txt" 2>/dev/null | sort
  echo '```'
} > "${R}_report.md"
echo "报告: ${R}_report.md"
