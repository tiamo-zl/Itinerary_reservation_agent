#!/usr/bin/env bash
# 依赖/镜像安全扫描。
#
# 需要：
#   pip-audit  （Python 依赖）
#   trivy      （镜像）或已登录的 docker scout
set -uo pipefail
cd "$(dirname "$0")/.."

status=0

echo "== Python dependencies =="
if command -v pip-audit >/dev/null 2>&1; then
  pip-audit --progress-spinner off || status=1
else
  echo "pip-audit not found. Install with: uv tool install pip-audit" >&2
  status=1
fi

echo
echo "== Frontend production dependencies =="
if npm --prefix web audit --omit=dev; then
  :
else
  status=1
fi

echo
echo "== Frontend all dependencies (dev included) =="
npm --prefix web audit || true

echo
echo "== Container image =="
# GHCR 匿名可拉；public.ecr.aws 在部分网络下会在 5 分钟内超时。
TRIVY_DB_REPOSITORY="${TRIVY_DB_REPOSITORY:-ghcr.io/aquasecurity/trivy-db:2}"
if command -v trivy >/dev/null 2>&1; then
  trivy image --severity HIGH,CRITICAL --timeout 15m \
    --exit-code 1 itinerary-reservation-agent:local || status=1
elif docker image inspect aquasec/trivy:latest >/dev/null 2>&1; then
  # 无需 Docker Hub 登录；缓存 DB，避免每次重复下载。
  docker run --rm \
    -e TRIVY_DB_REPOSITORY="$TRIVY_DB_REPOSITORY" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v trivy-cache:/root/.cache/trivy \
    aquasec/trivy:latest image --severity HIGH,CRITICAL --timeout 15m \
    --exit-code 1 --no-progress itinerary-reservation-agent:local || status=1
else
  echo "trivy not available. Install: brew install trivy" >&2
  echo "或拉取本地镜像：docker pull aquasec/trivy:latest" >&2
  status=1
fi

exit "$status"
