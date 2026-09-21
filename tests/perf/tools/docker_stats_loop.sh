#!/usr/bin/env bash
# 在 WSL 里每隔几秒采一次容器 CPU / 内存(docker stats --no-stream 本身要 ~2 s)。
# 用法(Windows 侧 run_load.sh 调用):wsl.exe -d Ubuntu-24.04 -u root -- bash /mnt/d/.../docker_stats_loop.sh <秒数> <输出文件(WSL 路径)>
DURATION="${1:-60}"
OUT="${2:-/tmp/docker_stats.txt}"
END=$(( $(date +%s) + DURATION ))
: > "$OUT"
while [ "$(date +%s)" -lt "$END" ]; do
  docker stats --no-stream --format "$(date +%T) {{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}} blockio={{.BlockIO}}" >> "$OUT" 2>/dev/null
  sleep 2
done
