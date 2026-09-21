#!/usr/bin/env bash
# 冷启动基础设施:删容器 + 删卷 → 重新 up → 等 healthy → 验证建表和种子数据确实由 init SQL 生成。
# 在 WSL/Linux 里执行:bash ops/smoke/cold_start.sh   (需在仓库任意位置运行,脚本自己定位 ops/)
set -euo pipefail
OPS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$OPS_DIR"
[ -f .env ] || cp .env.example .env

echo "== $(date +%T) down -v"
docker compose down -v --remove-orphans >/dev/null 2>&1 || true
echo "containers left: $(docker ps -a --format '{{.Names}}' | grep -c ticketqa || true)"
echo "volumes left:    $(docker volume ls --format '{{.Name}}' | grep -c '^ops_' || true)"

echo "== $(date +%T) up -d"
docker compose up -d
for i in $(seq 1 36); do
  sleep 5
  n=$(docker compose ps --format '{{.Name}} {{.Health}}' | grep -c healthy || true)
  [ "$n" -ge 4 ] && break
done
echo "== $(date +%T) status"
docker compose ps --format 'table {{.Name}}\t{{.Status}}'

echo "== init SQL 结果(新卷上必须已有 6 张表 + 6 个坐席,中文名 HEX 应为 E7AEA1E79086E59198)"
docker exec ticketqa-mysql mysql -uticketqa -pticketqa123 ticket_qa -N \
  -e "SELECT COUNT(*) AS tables_ FROM information_schema.tables WHERE table_schema='ticket_qa'; SELECT COUNT(*) FROM agent; SELECT HEX(display_name) FROM agent WHERE id=1;" 2>/dev/null
echo "== wiremock mappings: $(curl -s http://127.0.0.1:8089/__admin/mappings | grep -o '"total" *: *[0-9]*')"
echo "== DONE"
