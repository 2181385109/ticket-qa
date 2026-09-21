#!/usr/bin/env bash
# CI 用:在 service/ 目录后台起被测服务并等 /actuator/health 为 UP;已有实例(logs/app.pid)先停掉。
# 环境变量原样透传给 JVM(MYSQL_* / REDIS_* / RABBITMQ_* / APP_ATTACHMENT_DIR / HIKARI_MAX_POOL_SIZE …),
# 所以"用小池重启"只需要在 step 的 env 里给 HIKARI_MAX_POOL_SIZE(ADR-023)。
# 用法(在 service/ 下):bash ../.github/scripts/start-service.sh
set -euo pipefail
mkdir -p "${APP_ATTACHMENT_DIR:-/tmp/ticketqa-attachments}" logs
if [ -f logs/app.pid ] && kill -0 "$(cat logs/app.pid)" 2>/dev/null; then
  echo "stopping previous instance pid=$(cat logs/app.pid)"
  kill "$(cat logs/app.pid)"
  for i in $(seq 1 30); do kill -0 "$(cat logs/app.pid)" 2>/dev/null || break; sleep 1; done
fi
nohup java -Dfile.encoding=UTF-8 -jar target/ticket-qa-service-*.jar >> logs/stdout.log 2>&1 &
echo $! > logs/app.pid
for i in $(seq 1 60); do
  if curl -sf localhost:8080/actuator/health | grep -q '"status":"UP"'; then
    echo "service UP pid=$(cat logs/app.pid) HIKARI_MAX_POOL_SIZE=${HIKARI_MAX_POOL_SIZE:-<default 20>}"
    curl -s localhost:8080/actuator/prometheus | grep '^hikaricp_connections_max' || true
    exit 0
  fi
  sleep 2
done
echo "service did not come up"; tail -n 80 logs/stdout.log; exit 1
