# Runbook: 生产级 Trace 调用树与流转图

## 结论：去哪里看

| 视图 | 平台 | 入口 |
|---|---|---|
| Trace 调用树 / span 瀑布 | Grafana Explore → Tempo | http://127.0.0.1:13000/explore |
| 服务依赖 / 调用流转 | Grafana Tempo Service Graph | Explore → Tempo → Service Graph |
| Agent 编排节点流转 | Grafana Node Graph + 只读 PostgreSQL | http://127.0.0.1:13000/d/itinerary-trace-flow |
| LLM/Agent span 树 | Langfuse | http://127.0.0.1:13002 |
| SkyWalking 拓扑（可选） | SkyWalking Horizon/Lens | http://127.0.0.1:18080 |

自建 Vue 控制台的 `/trace`、`/flow` 仍是 frozen demo，不作为生产视图。

## 1. Trace 调用树（Grafana + Tempo）

前置条件：

```bash
OTEL_ENABLED=true
```

或使用：

```bash
make obs-up
```

因为 Tempo 只接收 OTel span；`OTEL_ENABLED=false` 时只会写 PostgreSQL
投影，不会进入 Tempo。

查询：

```text
Grafana → Explore → Tempo
TraceQL: { span.app.trace_id = "<X-Trace-Id>" }
```

也可以用：

```text
{ span.task_id = "<task_id>" }
{ name = "POST /chat" }
```

说明：

- API 返回的 `X-Trace-Id` 是应用 trace_id，不是 OTel SDK 生成的 trace ID；
- TraceRecorder 会把应用 trace_id 写入每个业务 span 的
  `app.trace_id` 属性，因此可以按 `X-Trace-Id` 搜索；
- FastAPI/HTTPX/psycopg/Redis 自动 span 作为子 span 出现在同一棵树中；
- Tempo live block 默认 5 分钟，最新 trace 可能要等一次 flush 才能被搜索到。

## 2. 服务依赖流转图（Tempo Service Graph）

### 配置

- Tempo：`metrics_generator` 开启 `service-graphs` + `span-metrics`，
  remote write 到 Prometheus。
- Prometheus：启用 `--web.enable-remote-write-receiver`。
- Grafana Tempo 数据源：

```yaml
jsonData:
  nodeGraph:
    enabled: true
  serviceMap:
    datasourceUid: prometheus
```

这些配置已写入：

```text
deploy/tempo/tempo.yaml
deploy/grafana/tempo-datasource.yml
```

同步到共享 monitoring-stack 后重启 Tempo/Prometheus/Grafana。

### 查看

```text
Grafana → Explore → Tempo → Service Graph
```

或查询 Prometheus：

```promql
traces_service_graph_request_total
traces_spanmetrics_calls_total
```

当前能看到：

- `user → itinerary-agent`（虚拟入口）
- `itinerary-agent → itinerary`（PostgreSQL）
- `itinerary-agent → redis`
- `user → mock-deps`（健康检查噪声，非业务调用）

### 限制

Service Graph 依赖 CLIENT/SERVER span 配对：

- api 的 FastAPI server span 已有；
- HTTPX client span 已有；
- mock-deps 已启用 OTel server span；
- DB/Redis 没有 server span，但 Tempo 仍能根据 database 语义生成边；
- 健康检查会形成 `user → mock-deps` 虚拟边，可忽略或在
  Tempo metrics-generator 中过滤。

## 3. Agent 编排流转图（Grafana Node Graph）

入口：

```text
http://127.0.0.1:13000/d/itinerary-trace-flow
```

使用：

1. 从 API 响应 `X-Trace-Id`、日志或 Tempo 复制应用 trace_id；
2. 在 dashboard 的 `Trace ID` 文本框输入；
3. Node Graph 显示本次实际走过的节点和边：

```text
understand → plan → search → policy → approval → confirm → book → respond
```

只显示实际执行节点；未执行的条件分支不画。

### 数据来源

只读 PostgreSQL 数据源 `itinerary_pg`，查询 `spans` 投影：

- nodes：`orchestration.node.*` span，按节点去重；
- edges：按 `start_time` 用 `LAG()` 生成相邻节点边；
- 连续重复节点（interrupt/resume 重跑）会去重。

这是业务投影图，不是 Tempo 原生 Service Graph，也不替代冻结控制台。

### 只读数据源初始化

```bash
./scripts/create-grafana-ro.sh
```

脚本会创建/更新 `grafana_ro` 只读角色，并打印密码。

把密码写入共享栈：

```text
monitoring-stack/grafana/provisioning/datasources/postgres.yml
```

仓库里的 `deploy/grafana/postgres-datasource.yml` 是占位模板，不要填真实密码后提交。

Grafana 需要能访问项目 Postgres：

- 共享 stack 的 Grafana 已加入 `itinerary-reservation-agent_default` 网络；
- 数据源地址使用 `postgres:5432`。

## 4. SkyWalking（可选）

当前 Collector 已向 SkyWalking 导出 OTLP；Horizon 的 trace tree/topology
需要原生 OTLP 服务目录。

如果 Horizon 原生服务目录仍为空：

- 以 Tempo Service Graph 作为生产拓扑主视图；
- 保留 SkyWalking 双跑兼容查询；
- 不阻塞 Grafana/Tempo 的 trace tree 和 Service Graph。

## 5. 排障

### Grafana 搜不到 trace

```bash
docker inspect itinerary-reservation-agent-api-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep OTEL_ENABLED
```

必须为 `true`。然后：

```bash
curl -s http://127.0.0.1:3200/ready
curl -s http://127.0.0.1:3200/metrics | grep tempo_distributor_spans_received_total
```

### 按 X-Trace-Id 搜不到

使用 TraceQL：

```text
{ span.app.trace_id = "<X-Trace-Id>" }
```

如果历史 trace 产生于 `app.trace_id` 属性加入之前，则只能用
`{ span.task_id = "<task_id>" }` 或按 root span 搜索。

### Service Graph 为空

检查：

- Tempo metrics-generator 是否启动：
  `tempo_metrics_generator_active_processors`
- Prometheus 是否有 `traces_service_graph_request_total`
- 是否有 CLIENT/SERVER 配对；无配对时不会产生边

### Node Graph 无数据

- 确认 trace_id 是应用 trace_id（X-Trace-Id），不是 OTel trace ID；
- 确认该 trace 有 `orchestration.node.*` span；
- 检查 Grafana 数据源 `itinerary_pg` health；
- 确认 `grafana_ro` 能 `SELECT spans`。

## 6. 相关文件

```text
deploy/tempo/tempo.yaml
deploy/grafana/tempo-datasource.yml
deploy/grafana/postgres-datasource.yml
deploy/grafana/dashboards/itinerary-trace-flow.json
scripts/create-grafana-ro.sh
```
