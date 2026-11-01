# 生产化改造进度（2026-11-01）

- 分支：`feat/observability-console`
- 测试：**117 passed**，覆盖率 **84.7%**
- 类型检查：`make typecheck` 覆盖 application/security/tools/workers/repositories
- 默认运行模式：`MODEL_MODE=scripted`、`ADAPTER_MODE=mock`、`AUTH_MODE=mock`

## 总体进度

| 阶段 | 状态 | 说明 |
|---|---|---|
| P0 生产基线 | ✅ 100% | PostgreSQL、worker/outbox、鉴权、API 加固、工具治理、保留清理、可观测与 CI 收尾完成 |
| P1 韧性与深度 | 约 20% | 五件套已接入；评测、HTTP mock、知识 CLI、前端、压测/混沌/安全未开始 |
| P2 规模化运维 | 0% | 未开始 |

## P0 明细

| 工作流 | 状态 | 已完成 | 剩余说明 |
|---|---|---|---|
| W0 配置/部署 | ✅ 100% | Dockerfile、Compose core、环境变量、`SecretStr` 密钥、生产鉴权/CORS/Host 校验 | — |
| W1 PostgreSQL | ✅ 100% | PostgreSQL + Alembic、仓储分层、Checkpoint、outbox、lease、SQL 边界测试 | 历史 SQLite Checkpoint 不迁移（既定非目标） |
| W2 Redis | ✅ 100% | 限流、LLM 缓存、故障降级、指标 | — |
| W3 鉴权/API | ✅ 100% | JWT/OIDC、request_id、限流、就绪探针、错误信封、CORS/TrustedHost、游标分页、SSE 心跳/超时/断连、scope 强制、任务/会话归属 | — |
| W4 Worker/Outbox | ✅ 100% | worker 分离、outbox relay、任务 lease、保留清理 worker、积压指标 | — |
| W5 模型网关 | ✅ 90% | fallback、结构化校验/修复、成本账本、缓存、超时 | 真流式、共享熔断、prompt 注册表属于 P1 |
| W6 工具治理 | ✅ 100% | 输入/输出 schema、超时、required_scopes、错误分类、工具指标、guard/审批/下单/幂等回放审计 | — |
| W7 可观测 | ✅ 100% | OTel、JSON 日志、Prometheus 指标、Postgres trace 投影、五件套、告警规则接入共享 Prometheus | SkyWalking 服务目录为空属外部栈限制，见下 |
| W8 测试/CI/文档 | ✅ 100% | 117 tests、84.7% 覆盖率、PG 测试库、ruff、mypy（新模块）、CI、ADR、Runbook | CI 尚未在 GitHub 实际运行 |

## 本轮（P0 收尾）完成项

### W0 / W3

- `JWT_SECRET`、模型 Key、DashScope Key、Milvus Token 改为 `SecretStr`。
- 生产环境启动校验：禁止 mock 鉴权、禁止通配符 CORS/Host、live 模式必须有主模型 Key。
- `CORSMiddleware` + `TrustedHostMiddleware`，顺序为 TrustedHost → CORS → auth，预检不进入鉴权。
- scope 强制：`chat`、`task:read`、`conversation:read`、`trace:read`、`approval:read/decide`、`feedback:write`、`badcase:manage`。
- 任务详情、任务恢复、会话消息改为用户级归属校验（管理员可跨用户）。
- 游标分页：`/traces`、`/tasks/summary`、`/conversations`、`/sessions`、`/approvals`、`/badcases`；默认 50，最大 200。
- SSE：15s 心跳、`X-Accel-Buffering: no`、断连取消、单轮超时、结构化 `error` 事件。

### W6

- 工具执行统一做 scope → 输入 schema → 超时 → handler → 输出 schema。
- 稳定错误码：`TOOL_NOT_FOUND`、`TOOL_FORBIDDEN`、`TOOL_TIMEOUT`、`TOOL_BAD_RESPONSE`、`TOOL_UNAVAILABLE`。
- 角色/scope 随任务写入 Checkpoint，恢复和 worker 路径不再依赖请求头。
- 审计覆盖：guard 拒绝、审批提交/决定、下单成功/失败、幂等回放；审计失败不阻断业务。

### W4 / W7

- 新增 `RetentionWorker`：span（默认 7 天）、已结束 outbox（30 天）、过期缓存、过期幂等键（7 天）。
- worker 就绪检查包含 `retention`；指标 `itinerary_retention_deleted_rows_total`。
- 新增 outbox 积压 gauge、工具调用/延迟指标。
- `deploy/prometheus/alerts.yml`：服务不可用、5xx、P95 延迟、模型 fallback、outbox 积压、工具错误、限流。
- 告警已挂载到共享 Prometheus（`/etc/prometheus/rules/itinerary-alerts.yml`），`/api/v1/rules` 可见 7 条规则。

## 当前运行

- 项目栈：API 8000、worker 8001、Web 8080、PostgreSQL 55432、Redis 56379
- OTel Collector：4317 / 4318 / 8889
- Prometheus：19090（已加载告警）
- Grafana：13000
- SkyWalking UI：18080
- Kibana：5601
- Langfuse：13002（web）/ 3030（worker）
- Mock IdP：9002（可选）

## Docker 文件布局

外部栈配置已集中到：

```text
/Users/lll/yuxiu/work_address_for_soft/docker/conf/
  monitoring-stack/
    docker-compose.yml
    prometheus/prometheus.yml
    prometheus/alerts.yml
  langfuse-stack/
```

- Langfuse compose 由现有容器反推生成，包含密钥，权限 `600`
- Named volumes 仍由 Docker 管理，不迁移到 `data/`
- 项目自身的 `Dockerfile`、`compose.yaml`、`deploy/`、`docker/postgres/init` 保留在仓库
- Higress 的 `/Users/lll/higress` 未迁移

## 已知限制

1. **SkyWalking 服务目录为空**：`sw_zipkin_span-*` 已有约 9.8k 文档，但 `sw_segment-*` 为 0，`getAllServices` 返回空。SkyWalking 11 的 OTLP/Zipkin trace 入库没有生成 segment；原始 span 可在 Elasticsearch/Kibana 中查询。已在 Runbook 记录，属于外部栈限制，不影响业务 Trace（Postgres 投影 + Langfuse 可用）。
2. **mypy 渐进覆盖**：application/security/tools/workers/repositories 通过；orchestration/infra 容器等旧模块尚未纳入严格检查，`make typecheck` 与 CI 使用同一范围。
3. Langfuse 与业务各有一套 Postgres/Redis，这是有意的故障域隔离，不建议合并。
4. `mock-idp` 仅 JWT 调试需要，可随时停止。

## 验证命令

```bash
make lint
make typecheck
TEST_DATABASE_URL=postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary_test make test
cd web && npm run build
```

本轮结果：

- `ruff check src tests`：通过
- `mypy`（CI 范围）：通过
- `pytest`：117 passed，84.7% 覆盖率
- Prometheus：7 条告警规则已加载

## 建议下一步（P1）

1. HTTP mock 服务 + 真实 HTTP 适配器 + 契约测试。
2. 模型真流式、共享熔断、prompt 版本注册表。
3. 评测金标集与 CI 阈值、badcase 回放。
4. 知识入库 CLI / 重建 / 校验。
5. 前端 JWT、错误边界、SSE 重连、Vitest/Playwright。
6. 压测 / 混沌 / 安全测试。
7. 视需要修复或替换 SkyWalking 服务目录查询。
