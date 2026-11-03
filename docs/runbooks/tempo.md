# Runbook: Grafana Tempo 主 Trace 后端

## 定位

- **Tempo 是生产主 Trace 后端**
- **SkyWalking 保留双跑兼容**，用于过渡期
- Langfuse 继续只接收带 `task_id` 的 LLM span
- 自建 Vue 控制台只是 demo 视图，不作为生产排障主入口

## 数据流

```text
API / worker --OTLP--> Collector
                         ├── otlp/tempo ─────▶ Tempo :4317
                         └── otlp/skywalking ▶ SkyWalking :11800
```

## 组件

| 组件 | 地址 |
|---|---|
| Tempo API | http://127.0.0.1:3200 |
| Tempo OTLP gRPC | 127.0.0.1:14317 |
| Tempo OTLP HTTP | 127.0.0.1:14318 |
| Grafana | http://127.0.0.1:13000 |
| Collector | 4317 / 4318 / 8889 |

Tempo 配置：`deploy/tempo/tempo.yaml`
Grafana 数据源：`deploy/grafana/tempo-datasource.yml`

## 启动

Tempo 与 Grafana 位于 monitoring stack：

```bash
docker compose \
  -f /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/docker-compose.yml \
  up -d tempo grafana
```

Collector 需要重新加载配置：

```bash
docker restart itinerary-reservation-agent-otel-collector-1
```

验证：

```bash
curl -s http://127.0.0.1:3200/ready
```

预期：

```text
ready
```

## 查询

查最近的 trace：

```bash
curl -s 'http://127.0.0.1:3200/api/search?limit=10'
```

按 service 过滤：

```bash
curl -s -G 'http://127.0.0.1:3200/api/search' \
  --data-urlencode 'tags=service.name="itinerary-agent"' \
  --data-urlencode 'limit=10'
```

按 trace ID 查完整 span：

```bash
curl -s 'http://127.0.0.1:3200/api/traces/<traceID>'
```

Grafana：

1. 打开 http://127.0.0.1:13000
2. Explore → 选择 `Tempo`
3. 按 service / trace ID / TraceQL 查询

Service Graph、Grafana Node Graph Agent 流转图见
`docs/runbooks/trace-viewing.md`。

## 保留

当前配置：

```yaml
backend_worker:
  compaction:
    block_retention: 720h   # 30 天
```

本地磁盘存储：

```text
/var/tempo/traces
/var/tempo/wal
```

数据在 Docker named volume `monitoring-stack_tempo-data`。

## 双跑与退役

当前同时导出到 Tempo 和 SkyWalking：

- Tempo：生产主后端
- SkyWalking：Zipkin 兼容查询，保留过渡期
- 退出条件满足后再停止 SkyWalking exporter

## 排查

### Tempo 未就绪

```bash
docker logs --tail 100 tempo
curl -s http://127.0.0.1:3200/ready
```

### Grafana 没有 Tempo 数据源

```bash
docker logs grafana 2>&1 | grep -i tempo
```

应看到：

```text
inserting datasource from configuration name=Tempo uid=tempo
```

### 有 Trace 但没有业务 span

检查：

- API/worker 的 `OTEL_ENABLED=true`
- Collector 能解析 `otel-collector`
- Tempo 的 `/api/traces/<id>` 中是否包含 `gateway.http`、`orchestration.node.*`

```bash
docker exec itinerary-reservation-agent-api-1 \
  python -c "import socket; print(socket.gethostbyname('otel-collector'))"
```

### 502/503 与 Trace 无关

Tempo 不可用不应影响业务；它只影响 Trace 查询。检查 Collector 的
`otelcol_exporter_send_failed_spans` 指标。
