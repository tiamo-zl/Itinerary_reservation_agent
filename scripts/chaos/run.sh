#!/usr/bin/env bash
# 基础混沌场景：
#   ./scripts/chaos/run.sh pg
#   ./scripts/chaos/run.sh redis
#   APPROVAL_ID=... TASK_ID=... ./scripts/chaos/run.sh worker
#   TASK_ID=... ./scripts/chaos/run.sh concurrent-resume
#
# 运行前请确认已停止正在进行的验收操作；脚本会在退出时尝试恢复依赖。
set -euo pipefail

cd "$(dirname "$0")/../.."
BASE="${BASE_URL:-http://127.0.0.1:8081}"
READY_TIMEOUT="${READY_TIMEOUT:-30}"

restore() {
  docker compose start postgres redis worker >/dev/null 2>&1 || true
}
trap restore EXIT

status_code() { curl -s -o /dev/null -w '%{http_code}' "$1"; }
ready() { status_code "$BASE/readyz"; }
wait_ready() {
  for _ in $(seq 1 "$READY_TIMEOUT"); do
    [ "$(ready)" = "200" ] && return 0
    sleep 1
  done
  echo "readyz 未恢复" >&2
  return 1
}
wait_task_status() {
  local task_id="$1" target="$2"
  for _ in $(seq 1 30); do
    local current
    current="$(curl -s "$BASE/tasks/$task_id" -H 'X-Mock-User: u001' \
      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status",""))')"
    [ "$current" = "$target" ] && return 0
    sleep 1
  done
  echo "task 未进入 $target" >&2
  return 1
}

case "${1:-}" in
  pg)
    echo "== 停 PostgreSQL =="
    docker compose stop postgres >/dev/null
    sleep 2
    [ "$(status_code "$BASE/healthz")" = "200" ] \
      && echo "healthz=200 OK" || { echo "healthz 异常"; exit 1; }
    [ "$(ready)" = "503" ] \
      && echo "readyz=503 OK" || { echo "readyz 未降级"; exit 1; }
    echo "== 恢复 PostgreSQL =="
    docker compose start postgres >/dev/null
    wait_ready
    echo "readyz=200 OK"
    ;;
  redis)
    echo "== 停 Redis =="
    docker compose stop redis >/dev/null
    sleep 1
    [ "$(status_code "$BASE/healthz")" = "200" ] \
      && echo "healthz=200 OK" || { echo "healthz 异常"; exit 1; }
    [ "$(ready)" = "503" ] \
      && echo "readyz=503 OK" || { echo "readyz 未降级"; exit 1; }
    echo "== 恢复 Redis =="
    docker compose start redis >/dev/null
    wait_ready
    echo "readyz=200 OK"
    ;;
  worker)
    : "${APPROVAL_ID:?需要 APPROVAL_ID}"
    : "${TASK_ID:?需要 TASK_ID}"
    echo "== 停 worker =="
    docker compose stop worker >/dev/null
    sleep 1
    curl -s -X POST "$BASE/admin/approvals/$APPROVAL_ID/approve" \
      -H 'X-Mock-User: u002' -H 'Content-Type: application/json' \
      -d '{"comment":"chaos worker"}' >/dev/null
    sleep 2
    current="$(curl -s "$BASE/tasks/$TASK_ID" -H 'X-Mock-User: u001' \
      | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status",""))')"
    [ "$current" = "WAITING_APPROVAL" ] \
      && echo "worker 停机时仍为 WAITING_APPROVAL OK" \
      || { echo "停机时状态异常: $current"; exit 1; }
    echo "== 启动 worker =="
    docker compose start worker >/dev/null
    wait_task_status "$TASK_ID" "WAITING_HUMAN"
    echo "worker 恢复后进入 WAITING_HUMAN OK"
    ;;
  concurrent-resume)
    : "${TASK_ID:?需要 TASK_ID}"
    echo "== 并发 resume =="
    for i in 1 2; do
      curl -s -N -X POST "$BASE/tasks/$TASK_ID/resume" \
        -H 'X-Mock-User: u001' -H 'Content-Type: application/json' \
        -d '{"action":"select","selected":{"flight_id":"f2","hotel_id":"h1"}}' \
        > "/tmp/chaos-resume-$i.log" 2>&1 &
    done
    wait
    if grep -q 'TASK_BUSY' /tmp/chaos-resume-1.log /tmp/chaos-resume-2.log; then
      echo "并发 resume 出现 TASK_BUSY OK"
    else
      echo "未观察到 TASK_BUSY，请检查任务是否已在 WAITING_HUMAN" >&2
      exit 1
    fi
    ;;
  *)
    echo "用法: $0 {pg|redis|worker|concurrent-resume}" >&2
    exit 2
    ;;
esac
