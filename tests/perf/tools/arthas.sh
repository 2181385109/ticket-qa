#!/usr/bin/env bash
# 以批处理方式对被测服务执行一条(或分号分隔的多条)Arthas 命令,输出去掉 banner,原样保留命令回显。
# 用法:bash tools/arthas.sh "<命令>" [输出文件]
#   bash tools/arthas.sh "dashboard -n 1"
#   bash tools/arthas.sh "trace com.ticketqa.ticket.TicketService grab -n 30" results/arthas_trace_grab.txt
# 前提:ARTHAS_BOOT 指向 arthas-boot.jar(首次会从 aliyun 下载 arthas 本体到 ~/.arthas);服务 pid 在 service/logs/app.pid。
# watch / trace / tt 这类命令会阻塞到 -n 次命中或 Ctrl-C,所以压测中采样时把它放后台、再发流量。
set -uo pipefail
CMD="${1:?arthas command}"
OUT="${2:-}"
[ -f "$(dirname "$0")/local.env" ] && . "$(dirname "$0")/local.env"   # 机器相关路径(见 local.env.example)
JAVA="${JAVA_HOME:+$JAVA_HOME/bin/}java"
BOOT="${ARTHAS_BOOT:?设置 ARTHAS_BOOT=arthas-boot.jar 的路径}"
PID_FILE="$(cd "$(dirname "$0")/../../.." && pwd)/service/logs/app.pid"
PID=$(tr -d '\r\n' < "$PID_FILE")
run() {
  "$JAVA" -jar "$BOOT" "$PID" -c "$CMD" 2>&1 \
    | sed -r 's/\x1b\[[0-9;]*m//g' \
    | awk 'BEGIN{p=0} /^\[arthas@/{p=1} p==1{print}'
}
if [ -n "$OUT" ]; then
  { echo "# $(date '+%F %T')  arthas pid=$PID"; echo "# 命令: $CMD"; run; } | tee "$OUT"
else
  run
fi
