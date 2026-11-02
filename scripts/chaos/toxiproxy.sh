#!/usr/bin/env bash
# 用法：
#   ./scripts/chaos/toxiproxy.sh setup
#   ./scripts/chaos/toxiproxy.sh latency [毫秒]
#   ./scripts/chaos/toxiproxy.sh reset
#   ./scripts/chaos/toxiproxy.sh down
#   ./scripts/chaos/toxiproxy.sh up
#
# 需要先启动 toxiproxy profile，并让 API 使用：
#   MOCK_DEPS_URL=http://toxiproxy:19003
set -euo pipefail

API="${TOXIPROXY_API:-http://127.0.0.1:8474}"
PROXY="${TOXIPROXY_PROXY:-mock-deps}"
UPSTREAM="${MOCK_DEPS_UPSTREAM:-mock-deps:9003}"
LISTEN="${MOCK_DEPS_LISTEN:-0.0.0.0:19003}"
LATENCY="${2:-2000}"

json() { python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin), ensure_ascii=False, indent=2))'; }

wait_api() {
  for _ in $(seq 1 20); do
    if curl -fsS "$API/version" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Toxiproxy API 不可用: $API" >&2
  exit 1
}

wait_api

case "${1:-}" in
  setup)
    curl -s -X DELETE "$API/proxies/$PROXY" >/dev/null || true
    curl -fsS -X POST "$API/proxies" \
      -H 'Content-Type: application/json' \
      -d "{\"name\":\"$PROXY\",\"listen\":\"$LISTEN\",\"upstream\":\"$UPSTREAM\",\"enabled\":true}" | json
    echo "Proxy $PROXY: $LISTEN -> $UPSTREAM"
    ;;
  latency)
    curl -fsS -X POST "$API/proxies/$PROXY/toxics" \
      -H 'Content-Type: application/json' \
      -d "{\"name\":\"latency_downstream\",\"type\":\"latency\",\"stream\":\"downstream\",\"toxicity\":1.0,\"attributes\":{\"latency\":$LATENCY,\"jitter\":0}}" | json
    echo "已注入 ${LATENCY}ms 延迟"
    ;;
  reset)
    curl -s -X DELETE "$API/proxies/$PROXY/toxics/latency_downstream" >/dev/null || true
    curl -s -X DELETE "$API/proxies/$PROXY/toxics/latency_upstream" >/dev/null || true
    echo "已清除注入的 toxics"
    ;;
  down)
    curl -fsS -X POST "$API/proxies/$PROXY" \
      -H 'Content-Type: application/json' \
      -d '{"enabled":false}' >/dev/null
    echo "Proxy $PROXY 已禁用"
    ;;
  up)
    curl -fsS -X POST "$API/proxies/$PROXY" \
      -H 'Content-Type: application/json' \
      -d '{"enabled":true}' >/dev/null
    echo "Proxy $PROXY 已启用"
    ;;
  *)
    echo "用法: $0 {setup|latency [ms]|reset|down|up}" >&2
    exit 2
    ;;
esac
