# Runbook: 结构化日志与 Trace 关联

## 数据流

```text
应用 JSON stdout
  → Docker json-file
  → OTel Collector filelog
  → json_parser（提升应用字段）
  → Elasticsearch data stream logs-itinerary
  → Kibana
```

## 字段

应用 JSON 字段现在位于：

```text
attributes.app.service
attributes.app.environment
attributes.app.version
attributes.app.trace_id
attributes.app.span_id
attributes.app.task_id
attributes.app.request_id
attributes.app.tenant_id
attributes.app.user_id
attributes.app.message
```

Docker 外壳字段：

```text
attributes.docker.stream
attributes.docker.time
```

日志时间使用 Docker 写入时间，不使用 Collector 摄取时间。

## Kibana 查询

打开 http://127.0.0.1:5601，选择 data stream `logs-itinerary`。

按 trace 精确查询：

```text
attributes.app.trace_id : "9729485662634defa38cf9528d8e5627"
```

按 task：

```text
attributes.app.task_id : "<task_id>"
```

按 request：

```text
attributes.app.request_id : "<request_id>"
```

错误：

```text
attributes.app.message : "ERROR"
```

> 旧数据仍然只有 `body.text`；结构化字段只对本次 Collector 重启后的新日志生效。

## `X-Trace-Id`

API 响应头现在返回 `X-Trace-Id`：

```bash
curl -i http://127.0.0.1:8081/conversations -H 'X-Mock-User: u001'
```

SSE `/chat` 与 `/tasks/{id}/resume` 在响应头返回对应的 trace，
与首个 `status` 事件中的 `trace_id` 一致。

用途：

- 用户/客服可以直接提供 trace
- 工单、反馈、评测用例可以带 trace 深链
- 日志、Tempo、控制台使用同一个连接键

## 验证

```bash
curl -N -s -X POST http://127.0.0.1:8081/chat \
  -H 'Content-Type: application/json' \
  -H 'X-Mock-User: u001' \
  -d '{"message":"log smoke","session_id":"log-smoke"}'
```

检查新日志字段：

```bash
curl -s 'http://127.0.0.1:9200/logs-itinerary/_search' \
  -H 'Content-Type: application/json' \
  -d '{"size":1,"query":{"exists":{"field":"attributes.app.trace_id"}}}'
```

## 限制

- Uvicorn access log 在 trace 上下文之外，`trace_id` 为空；
- 业务节点、模型、工具日志在 span 内，带 trace/task；
- 若需要所有访问日志也带 trace，需要在 ASGI 中间件层绑定 tracing context，
  这是后续可选项。
