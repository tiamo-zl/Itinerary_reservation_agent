#!/usr/bin/env bash
# 启动核心栈 + 五件套可观测。
# Langfuse 的 OTLP 使用 Basic 认证，自动从本机 Langfuse web 容器读取 key。
set -euo pipefail

cd "$(dirname "$0")/.."

if ! docker inspect langfuse-stack-langfuse-web-1 >/dev/null 2>&1; then
  echo "未找到 langfuse-stack-langfuse-web-1，请先启动 Langfuse stack。" >&2
  exit 1
fi

for c in prometheus grafana skywalking-oap elasticsearch; do
  if ! docker inspect "$c" >/dev/null 2>&1; then
    echo "未找到 $c，请先启动 monitoring-stack。" >&2
    exit 1
  fi
done

PUB=$(docker inspect langfuse-stack-langfuse-web-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | sed -n 's/^LANGFUSE_INIT_PROJECT_PUBLIC_KEY=//p' | head -1)
SEC=$(docker inspect langfuse-stack-langfuse-web-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | sed -n 's/^LANGFUSE_INIT_PROJECT_SECRET_KEY=//p' | head -1)

if [ -z "$PUB" ] || [ -z "$SEC" ]; then
  echo "Langfuse 容器缺少 INIT project key，无法配置 OTLP 认证。" >&2
  exit 1
fi

export LANGFUSE_AUTH="$(printf '%s:%s' "$PUB" "$SEC" | base64 | tr -d '\n')"
export OTEL_ENABLED="${OTEL_ENABLED:-true}"

exec docker compose --profile core --profile observability up -d "$@"
