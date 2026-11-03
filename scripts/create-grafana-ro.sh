#!/usr/bin/env bash
# 创建 Grafana 只读角色；密码不写入仓库。
#
# 用法：
#   GRAFANA_DB_PASSWORD='...' ./scripts/create-grafana-ro.sh
#   或直接运行，脚本会生成随机密码并打印。
set -euo pipefail

CONTAINER="${POSTGRES_CONTAINER:-itinerary-reservation-agent-postgres-1}"
DB_NAME="${POSTGRES_DB:-itinerary}"
DB_USER="${POSTGRES_USER:-itinerary}"
PW="${GRAFANA_DB_PASSWORD:-$(openssl rand -hex 16)}"

if ! [[ "$PW" =~ ^[A-Za-z0-9_.-]+$ ]]; then
  echo "GRAFANA_DB_PASSWORD 只能包含字母、数字、下划线、点和横线" >&2
  exit 1
fi

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "找不到容器 $CONTAINER；请先 make db-up" >&2
  exit 1
fi

SQL=$(cat <<EOF
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
    CREATE ROLE grafana_ro LOGIN PASSWORD '$PW';
  ELSE
    ALTER ROLE grafana_ro WITH LOGIN PASSWORD '$PW';
  END IF;
END
\$\$;
GRANT CONNECT ON DATABASE $DB_NAME TO grafana_ro;
GRANT USAGE ON SCHEMA public TO grafana_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro;
EOF
)

printf '%s' "$SQL" | docker exec -i "$CONTAINER" \
  psql -U "$DB_USER" -d "$DB_NAME"

echo
echo "grafana_ro 已就绪。Grafana 数据源密码：$PW"
echo "把 password 写入共享栈的 grafana/provisioning/datasources/postgres.yml。"
echo "不要提交这个密码。"
