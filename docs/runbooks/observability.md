# Runbook: five-piece observability

## Start

前置条件：

- Langfuse stack 的 `langfuse-stack-langfuse-web-1` 正在运行且已初始化项目 key；
- monitoring stack 的 `skywalking-oap`、`elasticsearch`、`prometheus` 正在运行；
- Docker 网络 `langfuse-stack_default`、`monitoring-stack_monitoring` 存在。

```bash
make obs-up
```

脚本会从 Langfuse web 容器读取 `LANGFUSE_INIT_PROJECT_*`，生成
`LANGFUSE_AUTH`，并设置 `OTEL_ENABLED=true` 后启动：

- core：PostgreSQL、Redis、API、worker、Web、migrate
- observability：OTel Collector、Prometheus、Grafana

也可以手动：

```bash
export LANGFUSE_AUTH="$(printf '%s:%s' "$PK" "$SK" | base64)"
export OTEL_ENABLED=true
docker compose --profile core --profile observability up -d
```

## URLs

| 系统 | 地址 | 用途 |
|---|---|---|
| Grafana | http://127.0.0.1:13001 | 指标看板（admin/admin，可通过 `GRAFANA_ADMIN_PASSWORD` 覆盖） |
| Prometheus | http://127.0.0.1:19091 | 原始指标与告警规则 |
| SkyWalking UI | http://127.0.0.1:18080 | Trace 查询 |
| Kibana | http://127.0.0.1:5601 | 日志检索，data stream `logs-itinerary` |
| Langfuse | http://127.0.0.1:3030 | Agent/LLM span 分析 |
| OTel Collector | 4317（gRPC）、4318（HTTP） | 应用 OTLP 入口 |

## 数据流

```text
API/worker --OTLP--> Collector
  traces --> SkyWalking（全部 span）
  traces --> Langfuse（仅带 task_id 的 agent span）
  logs   --> Elasticsearch（Docker json-file -> logs-itinerary data stream）
  metrics--> Prometheus exporter / 应用 /metrics 直接抓取
```

- Prometheus 直接抓取 `api:8000/metrics`、`worker:8001/metrics` 和 Collector 的 `:8889`。
- Grafana 自动加载 `Itinerary Agent` 看板。
- Langfuse 只保留带 `task_id` 的 span，避免 HTTP/DB 噪声。

## 故障排查

### Langfuse 401/404

- 确认 `LANGFUSE_AUTH` 是 `base64(public_key:secret_key)`；
- Langfuse v4 需要 `x-langfuse-ingestion-version: 4`，Collector 配置已带；
- 从 Collector 所在网络访问 `http://langfuse-web:3000/api/public/otel/v1/traces`。

### SkyWalking 没有数据

- 确认 `skywalking-oap` 开启了 `SW_OTEL_RECEIVER=default` 和
  `SW_RECEIVER_ZIPKIN=default`；
- 检查 `sw_zipkin_span-*` 索引是否有文档；
- OTel receiver 当前通过 Zipkin 转发，部分版本的服务目录查询可能为空，但原始 span 已落 ES。

### ELK 没有日志

- `logs-itinerary` 是 data stream；确认 `_data_stream/logs-itinerary` 存在；
- Collector 需要以 root 读取 `/var/lib/docker/containers`；
- 检查 Collector 日志中的 `elasticsearchexporter` 错误。

### 指标为空

- `curl http://127.0.0.1:19091/api/v1/targets` 应显示三个 job 都是 `up`；
- 应用 `/metrics` 必须可访问；worker 的端口是 8001。

## 外部栈注意事项

本仓库的 compose 依赖两个外部网络和容器，不负责创建它们：

- `langfuse-stack_default`（Langfuse v4 + ClickHouse + keeper）
- `monitoring-stack_monitoring`（SkyWalking、Elasticsearch、Prometheus、Grafana）

本地修复记录：

- Langfuse 的 ClickHouse keeper 配置目录曾被误建成目录，已改为文件；
- ClickHouse 复制表缺少 `{shard}`/`{replica}` 宏，已在 `config.d/keeper.xml` 补齐；
- 复制表元数据丢失时执行 `SYSTEM RESTORE REPLICA default.<table>`；
- monitoring 的 SkyWalking OAP 增加了 `SW_RECEIVER_ZIPKIN=default`。
