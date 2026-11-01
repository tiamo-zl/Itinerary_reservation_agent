#!/usr/bin/env bash
# 把项目接入本机已有的 Higress all-in-one。
#
# 前置：
#   - higress-ai 容器正在运行；
#   - core profile 已启动（api / web 容器存在）；
#   - 项目网络可通过 HIGRESS_NETWORK 覆盖。
#
# 功能：
#   1. 将 Higress 接入项目 Docker 网络（带 higress-edge 别名）；
#   2. 写入 McpBridge DNS registry 与 Ingress 路由；
#   3. 通过网关做 /healthz 和 /index.html 冒烟。
set -euo pipefail

cd "$(dirname "$0")/.."

HIGRESS_CONTAINER="${HIGRESS_CONTAINER:-higress-ai}"
HIGRESS_DATA_DIR="${HIGRESS_DATA_DIR:-/Users/lll/higress}"
HIGRESS_NETWORK="${HIGRESS_NETWORK:-itinerary-reservation-agent_default}"
HIGRESS_HTTP_PORT="${HIGRESS_HTTP_PORT:-8081}"
BACKUP_DIR="$HIGRESS_DATA_DIR/backups/$(date +%Y%m%d-%H%M%S)-higress"

if ! docker inspect "$HIGRESS_CONTAINER" >/dev/null 2>&1; then
  echo "未找到 $HIGRESS_CONTAINER" >&2
  exit 1
fi
if ! docker network inspect "$HIGRESS_NETWORK" >/dev/null 2>&1; then
  echo "未找到项目网络 $HIGRESS_NETWORK，请先启动 core profile。" >&2
  exit 1
fi

# 幂等接入项目网络；只有需要时才执行 network connect。
if ! docker inspect "$HIGRESS_CONTAINER" \
    --format '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' \
    | grep -qx "$HIGRESS_NETWORK"; then
  docker network connect --alias higress-edge "$HIGRESS_NETWORK" \
    "$HIGRESS_CONTAINER"
fi

mkdir -p "$BACKUP_DIR"
cp -a "$HIGRESS_DATA_DIR/mcpbridges" "$BACKUP_DIR/" 2>/dev/null || true
cp -a "$HIGRESS_DATA_DIR/ingresses" "$BACKUP_DIR/" 2>/dev/null || true
cp -a "$HIGRESS_DATA_DIR/configmaps/higress-config.yaml" \
  "$BACKUP_DIR/" 2>/dev/null || true

# 项目容器重建后 IP 会变化。默认 200s 的 DNS 刷新太慢，改成 10s；
# 只有首次修改时重启 Higress 让 mesh 配置生效。
NEED_RESTART=0
if grep -q 'dnsRefreshRate: 200s' \
    "$HIGRESS_DATA_DIR/configmaps/higress-config.yaml" 2>/dev/null; then
  python3 - "$HIGRESS_DATA_DIR/configmaps/higress-config.yaml" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
path.write_text(
    path.read_text().replace("dnsRefreshRate: 200s", "dnsRefreshRate: 10s")
)
PY
  NEED_RESTART=1
fi

mkdir -p "$HIGRESS_DATA_DIR/mcpbridges" "$HIGRESS_DATA_DIR/ingresses"
cp deploy/higress/mcpbridge-default.yaml \
  "$HIGRESS_DATA_DIR/mcpbridges/default.yaml"
cp deploy/higress/ingress-api.yaml \
  "$HIGRESS_DATA_DIR/ingresses/itinerary-api.yaml"
cp deploy/higress/ingress-web.yaml \
  "$HIGRESS_DATA_DIR/ingresses/itinerary-web.yaml"
cp deploy/higress/ingress-console.yaml \
  "$HIGRESS_DATA_DIR/ingresses/default.yaml"
# 早期探测路由不再需要。
rm -f "$HIGRESS_DATA_DIR/ingresses/itinerary-api-probe.yaml" \
      "$HIGRESS_DATA_DIR/ingresses/itinerary-web-probe.yaml"

if [ "$NEED_RESTART" = 1 ]; then
  echo "dnsRefreshRate 已改为 10s，重启 Higress 使 mesh 配置生效..."
  docker restart "$HIGRESS_CONTAINER" >/dev/null
  sleep 8
fi

echo "等待 Higress 应用配置..."
for _ in $(seq 1 20); do
  if curl -fsS -m 2 "http://127.0.0.1:$HIGRESS_HTTP_PORT/healthz" \
      >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS -m 5 "http://127.0.0.1:$HIGRESS_HTTP_PORT/healthz"
echo
curl -fsS -m 5 -o /dev/null \
  "http://127.0.0.1:$HIGRESS_HTTP_PORT/index.html"
echo "Higress OK: http://127.0.0.1:$HIGRESS_HTTP_PORT"
