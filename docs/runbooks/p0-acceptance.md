# P0 验收与观测手册

本手册用于人工验收 P0 生产基线：功能链路、数据一致性、鉴权、降级和可观测。
所有命令默认在本仓库根目录执行，外部系统仍为 mock。

## 0. 入口与环境

| 系统 | 地址 | 用途 |
|---|---|---|
| Higress 网关 | http://127.0.0.1:8081 | **统一入口** |
| Web 直连 | http://127.0.0.1:8080 | 备用入口，绕过网关 |
| API 直连 | http://127.0.0.1:8000 | 调试、`/docs`、`/metrics` |
| Worker | http://127.0.0.1:8001 | 就绪与指标 |
| PostgreSQL | 127.0.0.1:55432 | 业务库、checkpoint、outbox、trace 投影 |
| Redis | 127.0.0.1:56379 | 限流、LLM 缓存 |
| mock-deps | 127.0.0.1:9003 | `ADAPTER_MODE=http` 时的外部依赖 |
| mock IdP | 127.0.0.1:9002 | JWT 调试（可选） |

可观测：

| 系统 | 地址 |
|---|---|
| Grafana | http://127.0.0.1:13000 |
| Prometheus | http://127.0.0.1:19090 |
| Kibana | http://127.0.0.1:5601 |
| Langfuse | http://127.0.0.1:13002 |
| SkyWalking UI | http://127.0.0.1:18080 |
| OTel Collector | 4317（gRPC）/ 4318（HTTP）/ 8889（指标） |

### 当前运行模式

```bash
docker inspect itinerary-reservation-agent-api-1 \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'ADAPTER_MODE|MODEL_MODE|AUTH_MODE'
```

- 默认 core：`ADAPTER_MODE=mock`、`MODEL_MODE=scripted`、`AUTH_MODE=mock`
- 当前可能运行在 `ADAPTER_MODE=http`（P1 HTTP mock 模式）
- **演示数据的创建模式必须与 API 模式一致**，见第 2 节

## 1. 启动与健康检查

```bash
make db-up
make migrate
docker compose --profile core up -d --build
make higress-up
```

检查：

```bash
curl -fsS http://127.0.0.1:8081/healthz
curl -fsS http://127.0.0.1:8081/readyz
curl -fsS http://127.0.0.1:8001/readyz
```

预期：

- API `/readyz`：`database/redis/checkpointer` 全部 `ok`
- Worker `/readyz`：额外包含 `outbox_relay: ok`、`retention: ok`
- 网关 `/` 与 `/index.html` 返回 200

## 2. 生成演示数据

脚本化模型默认没有脚本，直接在新对话里发消息不会走到审批。用 demo seed
创建一条完整任务：

```bash
# mock 模式（默认 core）
make demo-seed

# 当前 API 是 ADAPTER_MODE=http 时
make demo-seed ARGS="--adapter-mode http --trace-id p0-manual-trace --session p0-manual"
```

输出示例：

```text
task_id: 85bf6eefa5704e7b8bb886bb0ec3d17e
trace_id: p0-manual-trace
session_id: p0-manual
status: WAITING_APPROVAL
approval_id: a6dbf800114c44a7a58d374954694bcd
interrupt: approval
```

建议把输出保存到变量：

```bash
PYTHONPATH=src uv run python scripts/seed_demo_task.py \
  --adapter-mode http --json > /tmp/p0-demo.json

TASK_ID=$(python3 -c 'import json;print(json.load(open("/tmp/p0-demo.json"))["task_id"])')
TRACE_ID=$(python3 -c 'import json;print(json.load(open("/tmp/p0-demo.json"))["trace_id"])')
APPROVAL_ID=$(python3 -c 'import json;print(json.load(open("/tmp/p0-demo.json"))["approval_id"])')
```

> 如果先以 mock 模式创建，再切到 http 模式，审批单只存在本地投影中，
> mock-deps 里没有对应记录，审批会失败。切换模式后请重新 seed。

## 3. 功能验收

### 3.1 控制台

| 页面 | 地址 | 检查点 |
|---|---|---|
| 对话 | http://127.0.0.1:8081/ | 能进入聊天页 |
| 对话记录 | http://127.0.0.1:8081/conversations | 能看到 seed 的会话 |
| 审批工作台 | http://127.0.0.1:8081/approvals | 能看到 pending 审批 |
| 流转图 | `http://127.0.0.1:8081/flow/$TRACE_ID` | 节点/边、审批信息 |
| Trace 回放 | `http://127.0.0.1:8081/trace/$TRACE_ID` | 调用树、Checkpoint 历史、反馈 |
| 线上概览 | http://127.0.0.1:8081/overview | trace 数、错误率、分层延迟 |

### 3.2 任务与审批 API

```bash
curl -s http://127.0.0.1:8081/tasks/$TASK_ID \
  -H 'X-Mock-User: u001' | python3 -m json.tool
# 预期 status=WAITING_APPROVAL

curl -s 'http://127.0.0.1:8081/approvals?status=pending' \
  -H 'X-Mock-User: u002' | python3 -m json.tool
# 预期能看到 $APPROVAL_ID
```

管理员通过：

```bash
curl -s -X POST \
  http://127.0.0.1:8081/admin/approvals/$APPROVAL_ID/approve \
  -H 'X-Mock-User: u002' \
  -H 'Content-Type: application/json' \
  -d '{"comment":"P0 验收通过"}' | python3 -m json.tool
```

等待 worker 恢复（默认 1s 轮询）：

```bash
for i in $(seq 1 15); do
  task_status=$(curl -s http://127.0.0.1:8081/tasks/$TASK_ID \
    -H 'X-Mock-User: u001' | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')
  echo "$task_status"
  [ "$task_status" = "WAITING_HUMAN" ] && break
  sleep 1
done
```

预期进入 `WAITING_HUMAN`，说明 outbox → lease → Checkpoint 恢复链路正常。

### 3.3 用户确认并下单

```bash
curl -N -s -X POST \
  http://127.0.0.1:8081/tasks/$TASK_ID/resume \
  -H 'X-Mock-User: u001' \
  -H 'Content-Type: application/json' \
  -d '{"action":"select","selected":{"flight_id":"f2","hotel_id":"h1"}}'
```

预期 SSE 最后出现：

```text
event: result
data: {..., "status": "COMPLETED"}
```

### 3.4 修改需求 / 取消

在 `WAITING_HUMAN` 状态下修改需求：

```bash
curl -N -s -X POST \
  http://127.0.0.1:8081/tasks/$TASK_ID/resume \
  -H 'X-Mock-User: u001' \
  -H 'Content-Type: application/json' \
  -d '{"action":"modify","amended_request":{"origin_city":"上海","destination_city":"上海","start_date":"2026-11-10","end_date":"2026-11-12"}}'
```

预期：

- 任务 `revision` 增加 1
- 旧 options/approval/selected 清空
- 重新进入规划/审批流程

取消：

```bash
curl -N -s -X POST \
  http://127.0.0.1:8081/tasks/$TASK_ID/resume \
  -H 'X-Mock-User: u001' \
  -H 'Content-Type: application/json' \
  -d '{"action":"cancel"}'
```

预期 `status=CANCELLED`，之后该任务不再允许动作。

### 3.5 反馈与 badcase

```bash
curl -s -X POST http://127.0.0.1:8081/feedback \
  -H 'X-Mock-User: u001' \
  -H 'Content-Type: application/json' \
  -d '{"trace_id":"'$TRACE_ID'","task_id":"'$TASK_ID'","category":"plan","severity":"medium","comment":"P0 验收反馈"}'

curl -s 'http://127.0.0.1:8081/badcases?status=open' \
  -H 'X-Mock-User: u002' | python3 -m json.tool
```

预期：员工可提交反馈；管理员可查看 badcase；手机号/证件号会被脱敏。

## 4. 数据一致性与并发

### 4.1 重启 API 后 Checkpoint 仍可读

```bash
docker compose restart api
sleep 3
curl -s http://127.0.0.1:8081/tasks/$TASK_ID \
  -H 'X-Mock-User: u001'
curl -s "http://127.0.0.1:8081/tasks/$TASK_ID/history?limit=5" \
  -H 'X-Mock-User: u001'
```

预期：任务和 Checkpoint 历史仍然存在（PostgreSQL 持久化）。

### 4.2 worker 停机时审批不丢

```bash
docker compose stop worker
# 在审批页通过 $APPROVAL_ID，或使用上面的 approve curl
# 此时任务应保持 WAITING_APPROVAL

docker compose start worker
# 等待后任务应进入 WAITING_HUMAN
```

### 4.3 重复审批不重复恢复

对同一审批单调用两次 approve，然后检查：

```bash
docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT id, status, aggregate_id, created_at FROM outbox WHERE aggregate_id='$APPROVAL_ID' ORDER BY id;"
```

预期：可能有多条 outbox（至少一次投递），但任务只会被恢复一次；
第二次事件会因任务已不在 `WAITING_APPROVAL` 而跳过。

### 4.4 并发 resume 只成功一次

在 `WAITING_HUMAN` 状态下并发两次：

```bash
for i in 1 2; do
  curl -s -N -X POST \
    http://127.0.0.1:8081/tasks/$TASK_ID/resume \
    -H 'X-Mock-User: u001' \
    -H 'Content-Type: application/json' \
    -d '{"action":"select","selected":{"flight_id":"f2","hotel_id":"h1"}}' &
done
wait
```

预期：一个请求完成，另一个收到 `TASK_BUSY` 错误事件（任务 lease 生效）。

### 4.5 审计 / 幂等 / outbox

```bash
docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT action, decision, actor, reason, created_at FROM audit_log WHERE task_id='$TASK_ID' ORDER BY created_at;"

docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT key, created_at FROM idempotency WHERE key LIKE '$TASK_ID:%';"

docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT status, COUNT(*) FROM outbox GROUP BY status;"
```

预期：

- `audit_log` 包含 `check_policy`、`approval.decide`、`book_flight`、`book_hotel`
- 下单只产生一次 `idempotency` 记录，重复执行返回 `replayed`
- outbox 最终为 `done`，积压为 0

## 5. 鉴权与安全

### 5.1 mock 用户

| 用户 | 租户 | 角色 |
|---|---|---|
| `u001` | demo-company | employee |
| `u002` | demo-company | employee + approver |
| `u003` | other-company | employee |

### 5.2 跨租户/跨用户

```bash
# u003 不能读 u001 的任务
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8081/tasks/$TASK_ID -H 'X-Mock-User: u003'
# 预期 403

# u003 不能恢复 u001 的任务
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  http://127.0.0.1:8081/tasks/$TASK_ID/resume \
  -H 'X-Mock-User: u003' -H 'Content-Type: application/json' \
  -d '{"action":"cancel"}'
# 预期 403
```

### 5.3 JWT 模式（可选）

```bash
export JWT_SECRET='p0-manual-secret-0123456789abcdef'
export AUTH_MODE=jwt
docker compose --profile core --profile mocks up -d mock-idp api worker

TOKEN=$(curl -s -X POST http://127.0.0.1:9002/token \
  -H 'Content-Type: application/json' \
  -d '{"user":"u002"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s http://127.0.0.1:8081/conversations \
  -H "Authorization: Bearer $TOKEN" | head
# 预期 200；无 token 时 401
```

恢复 mock 模式：

```bash
unset AUTH_MODE JWT_SECRET
docker compose --profile core up -d api worker
```

### 5.4 限流

```bash
for i in $(seq 1 21); do
  curl -s -o /dev/null -w '%{http_code}\n' \
    -X POST http://127.0.0.1:8081/feedback \
    -H 'X-Mock-User: u001' -H 'Content-Type: application/json' \
    -d '{"trace_id":"p0-rate-limit"}'
done | sort | uniq -c
```

预期：约 20 个 200，1 个 429；429 响应带 `Retry-After`。

### 5.5 CORS 预检

```bash
curl -i -X OPTIONS http://127.0.0.1:8081/chat \
  -H 'Origin: http://localhost:5211' \
  -H 'Access-Control-Request-Method: POST'
```

预期：200，包含 `Access-Control-Allow-Origin: http://localhost:5211`。

## 6. 降级验收

### 6.1 停 PostgreSQL

```bash
docker compose stop postgres
curl -s -o /dev/null -w 'healthz=%{http_code}\n' http://127.0.0.1:8081/healthz
curl -s -o /dev/null -w 'readyz=%{http_code}\n' http://127.0.0.1:8081/readyz
# 预期 healthz=200, readyz=503
docker compose start postgres
```

### 6.2 停 Redis

```bash
docker compose stop redis
curl -s -o /dev/null -w 'readyz=%{http_code}\n' http://127.0.0.1:8081/readyz
# 预期 503；聊天读路径 fail-open，审批限流 fail-closed
docker compose start redis
```

### 6.3 模型/工具降级

离线模式不调用真实模型；可用测试覆盖：

```bash
uv run pytest -q tests/test_model_gateway.py tests/test_scenarios.py -k "failure or degraded or fallback"
```

HTTP 模式可用 `X-Mock-Fault` 注入 500/429/timeout：

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:9003/users/u001 -H 'X-Mock-Fault: 500'
```

## 7. 观测方案

### 7.1 数据流

```text
API / Worker
  ├── /metrics ───────────────▶ Prometheus ──▶ Grafana
  ├── OTLP :4317/:4318 ───────▶ OTel Collector
  │                               ├── traces ──▶ SkyWalking（原始 span 落 ES）
  │                               ├── traces ──▶ Langfuse（只保留带 task_id 的 span）
  │                               └── metrics ─▶ Prometheus :8889
  └── JSON stdout ─────────────▶ Docker json-file ──▶ Collector filelog ──▶ Elasticsearch ──▶ Kibana

PostgreSQL spans 投影 ──▶ 自建控制台（流转图/Trace 回放）
```

### 7.2 Grafana

1. 打开 http://127.0.0.1:13000，用本机 Grafana 管理员账号登录。
2. 打开看板 **Itinerary Agent**（UID `itinerary-agent`）。
3. 时间范围设为 `Last 15 minutes`，刷新 `10s`。

看板面板：

| 面板 | 观察点 |
|---|---|
| HTTP requests by status | 验收请求是否产生 2xx；注入错误时 4xx/5xx |
| HTTP p95 latency | 聊天/审批/trace 查询延迟 |
| Model calls by provider/status | 模型调用量、失败、fallback |
| Rate limited requests | 限流触发 |
| Outbox events | 审批恢复事件完成/失败 |
| Active SSE connections | 打开聊天/恢复流时应 >0，断开后回 0 |

验收动作与面板对应：

- 调用 `/chat` → HTTP requests + SSE connections
- 审批通过 → Outbox events done
- 连续 21 次 feedback → Rate limited requests 增加
- 主模型失败（live 模式）→ Model calls 出现 fallback

### 7.3 Prometheus

- Targets：http://127.0.0.1:19090/targets
  - `itinerary-api`、`itinerary-worker`、`otel-collector` 必须 `up`
- Rules：http://127.0.0.1:19090/rules
  - `itinerary-agent` 组应有 8 条规则

常用查询：

```promql
up{job=~"itinerary-(api|worker)"}

sum by (status) (rate(itinerary_http_requests_total[5m]))

histogram_quantile(
  0.95,
  sum by (le) (rate(itinerary_http_request_duration_seconds_bucket[5m]))
)

sum by (provider, status) (rate(itinerary_model_calls_total[5m]))
sum(rate(itinerary_model_calls_total{fallback="True"}[5m]))

itinerary_outbox_backlog

sum by (tool, status, code) (rate(itinerary_tool_calls_total[5m]))

itinerary_retention_deleted_rows_total
```

告警验证（可选）：

- `docker compose stop api`，约 2 分钟后 `ItineraryServiceDown` 进入 firing；
- 恢复 API 后自动恢复。
- 不要在共享环境长时间保留故障。

### 7.4 Kibana

1. 打开 http://127.0.0.1:5601。
2. 创建/选择 data view：`logs-itinerary`（data stream）。
3. 时间范围选择验收时间段。
4. 在 Discover 中搜索。

当前 Elasticsearch 中文档结构是：

- `@timestamp`
- `attributes.docker.stream/time`
- `body.text`：应用输出的 JSON 字符串

因此使用全文检索：

```text
body.text : "p0-manual-trace"
body.text : "ERROR"
body.text : "<request_id>"
```

应用 JSON 内的字段（`trace_id`、`span_id`、`task_id`、`request_id`、
`tenant_id`、`user_id`）目前位于 `body.text` 字符串内，全文检索可用；
后续可在 Collector filelog 中增加一次 `json_parser` 把它们提升为结构化字段。

排查：

```bash
curl -s 'http://127.0.0.1:9200/_data_stream/logs-itinerary?pretty'
curl -s 'http://127.0.0.1:9200/logs-itinerary/_count?pretty'
docker logs --tail 100 itinerary-reservation-agent-otel-collector-1
```

### 7.5 Langfuse

1. 打开 http://127.0.0.1:13002，登录本机 Langfuse 项目。
2. 进入 **Tracing / Traces**。
3. 按 `task_id` 搜索 `$TASK_ID`，或按时间范围筛选。
4. 查看：
   - trace 层级与 span 时间
   - LLM generation 的 token、延迟、成本
   - 模型名、provider、fallback 标记

说明：

- Collector 只把带 `task_id` 的 span 发给 Langfuse，HTTP/DB 噪声不会进入。
- 默认 `CAPTURE_PROMPT=false`，不会保存完整 prompt/completion；需要看内容时显式开启。
- 若为空：
  - 检查 Collector 日志中的 `otlphttp/langfuse` 错误；
  - 检查 `LANGFUSE_AUTH` 是否为 `base64(public:secret)`；
  - 确认 Langfuse v4 的 `x-langfuse-ingestion-version: 4` 头存在。

### 7.6 SkyWalking

打开 http://127.0.0.1:18080。

**已知限制**：当前 SkyWalking 11.0.0 把 OTLP/Zipkin span 写入
`sw_zipkin_span-*`，但未生成 `sw_segment`，服务目录查询为空。
因此：

- 业务链路以自建控制台（Postgres 投影）和 Langfuse 为准；
- SkyWalking 只用于确认原始 span 是否到达。

验证原始 span：

```bash
curl -s 'http://127.0.0.1:9200/_cat/indices/sw_zipkin_span-*?h=index,docs.count'
curl -s 'http://127.0.0.1:9200/sw_zipkin_span-*/_search?size=1&pretty'
```

### 7.7 OTel Collector

端口：

- 4317：OTLP gRPC
- 4318：OTLP HTTP
- 8889：Collector 自身 Prometheus 指标

检查 Collector 指标：

```promql
sum(rate(otelcol_receiver_accepted_spans[5m]))
sum(rate(otelcol_exporter_sent_spans[5m]))
sum(rate(otelcol_exporter_send_failed_spans[5m]))
```

查看日志：

```bash
docker logs --tail 100 itinerary-reservation-agent-otel-collector-1
```

确认数据流：

1. 触发一次 `/chat` 或 resume；
2. `otelcol_receiver_accepted_spans` 增加；
3. Langfuse 出现带 `task_id` 的 trace；
4. ES `sw_zipkin_span-*` 文档增加；
5. Kibana 出现该 trace 的日志。

## 8. 自动化验收

```bash
make lint
make typecheck
TEST_DATABASE_URL=postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary_test make test
make eval
```

当前基线：

- `131 passed`
- 覆盖率 **85.5%**
- `make eval` 全部 suite 通过

## 9. 验收记录模板

| 项目 | 结果 | 证据 |
|---|---|---|
| 网关/健康检查 | ✅/❌ | `/healthz`、`/readyz` |
| 对话 → 审批 → 恢复 → 下单 | ✅/❌ | task_id / trace_id / approval_id |
| API 重启后 Checkpoint | ✅/❌ | `/tasks/{id}/history` |
| worker 停机恢复 | ✅/❌ | outbox 状态变化 |
| 重复审批/并发 resume | ✅/❌ | 只有一次恢复，另一个 TASK_BUSY |
| 跨租户访问 | ✅/❌ | 403 |
| 限流/CORS | ✅/❌ | 429 / CORS 头 |
| PG/Redis 降级 | ✅/❌ | readyz 503 |
| Grafana/Prometheus | ✅/❌ | 面板与 target |
| Kibana/Langfuse | ✅/❌ | 日志与 trace |
| 自动化测试/评测 | ✅/❌ | test/eval 输出 |

## 10. 常见问题

| 现象 | 处理 |
|---|---|
| 新建对话没有审批 | 脚本模型为空，使用 `make demo-seed` |
| 审批通过后任务不变 | 检查 worker 是否运行；`/readyz` 的 outbox_relay |
| 网关 503 | 检查 api/web 是否在项目网络；`make higress-up` |
| Kibana 无日志 | 检查 data stream 和 Collector filelog 权限 |
| Langfuse 无 trace | 检查带 task_id 的 span、LANGFUSE_AUTH、网络 |
| SkyWalking 服务为空 | 已知外部栈限制，改用控制台/Langfuse |
| Grafana 登录失败 | 使用本机 Grafana 管理员账号；密码不在仓库 |
