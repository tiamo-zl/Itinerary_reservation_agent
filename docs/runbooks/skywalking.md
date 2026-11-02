# Runbook: SkyWalking OTLP/Zipkin 查询

## 背景

SkyWalking 11 的 OTLP receiver 会把 OTLP span 转成 Zipkin span 存入
`sw_zipkin_span-*`，不会进入原生 segment/OAL 分析。

因此：

- 原生 `getAllServices` 为空是设计行为，不是数据丢失；
- 服务、span、trace 应通过 **Zipkin v2 查询 API** 读取；
- Zipkin 数据只用于兼容展示，不参与 SkyWalking 原生指标分析。

## 配置

`monitoring-stack/docker-compose.yml` 的 `skywalking-oap`：

```yaml
environment:
  - SW_OTEL_RECEIVER=default
  - SW_OTEL_RECEIVER_ENABLED_HANDLERS=otlp,otlp-metrics,otlp-logs,otlp-traces
  - SW_RECEIVER_ZIPKIN=default
  - SW_QUERY_ZIPKIN=default
ports:
  - "19412:9412"   # Zipkin v2 查询 API
```

应用：

```bash
docker compose -f /Users/lll/yuxiu/work_address_for_soft/docker/conf/monitoring-stack/docker-compose.yml \
  up -d skywalking-oap
```

## 验证

```bash
curl -s http://127.0.0.1:19412/zipkin/api/v2/services
```

预期包含：

```json
["itinerary-agent","probe-svc"]
```

查询 span 名称：

```bash
curl -s 'http://127.0.0.1:19412/zipkin/api/v2/spans?serviceName=itinerary-agent&limit=20'
```

查询 trace：

```bash
curl -s 'http://127.0.0.1:19412/zipkin/api/v2/traces?serviceName=itinerary-agent&limit=10'
```

查询某个 trace：

```bash
curl -s 'http://127.0.0.1:19412/zipkin/api/v2/trace/<traceId>'
```

## 已知限制

- SkyWalking Horizon UI 的服务目录仍可能为空，因为它读取原生 segment；
- Zipkin 查询 API 可用，但原生 UI 不展示 Zipkin 数据；
- 如需 UI，可接 Zipkin Lens 或自定义查询页；
- 业务 Trace 仍以自建控制台（Postgres 投影）和 Langfuse 为主。

## 数据流

```text
API/worker --OTLP--> Collector --OTLP/gRPC--> SkyWalking OAP
                                              ├── sw_zipkin_span-*（ES）
                                              └── Zipkin v2 API :19412
```
