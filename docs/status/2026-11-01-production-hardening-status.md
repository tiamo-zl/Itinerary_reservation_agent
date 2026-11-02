# 生产化改造进度（2026-11-01）

- 分支：`feat/observability-console`
- 最新提交：`6347b72 fix: isolate config defaults test from CI environment`
- 测试：**138 passed**，覆盖率 **83.8%**
- 评测：`make eval` 全部通过（66 条金标/回放用例）
- 类型检查：`make typecheck` 覆盖 application/eval/knowledge/security/tools/workers/repositories
- 默认运行模式：`MODEL_MODE=scripted`、`ADAPTER_MODE=mock`、`AUTH_MODE=mock`

## 当前快照（2026-11-01 22:37 CST）

- 工作树：只剩用户本地文件未提交
  - `src/itinerary_agent/api/static/chat.html`
  - `web/vite.config.ts`
  - `docs/reviews/`
- 当前运行的 API/worker：`ADAPTER_MODE=http`、`MODEL_MODE=scripted`、`AUTH_MODE=mock`
- 当前运行镜像早于最新模型网关改动；重建因 Docker 内 `uv sync` 下载依赖长时间停住而中止。
  最新代码已通过测试，重新构建命令：

  ```bash
  ADAPTER_MODE=http MOCK_DEPS_URL=http://mock-deps:9003 \
    docker compose --profile core --profile mocks up -d --build api worker mock-deps
  ```

- 演示数据：
  - `p0-manual`：task `85bf6eefa5704e7b8bb886bb0ec3d17e`，trace `p0-manual-trace`，
    approval `a6dbf800114c44a7a58d374954694bcd`，状态 `WAITING_HUMAN`（已用于 worker 停机/并发 resume 混沌）
  - `p0-verify`：已走完审批 → 恢复 → 选择 → `COMPLETED`
- 观测：
  - Prometheus 7 个 target `up`
  - 8 条告警规则已加载
  - Grafana `Itinerary Agent` 看板已 provision
  - Tempo 主 Trace 已接入，Grafana 已加载 Tempo 数据源
  - SkyWalking Zipkin 查询 API 已启用（19412），双跑兼容
  - Horizon 原生服务目录仍为空（Zipkin 兼容数据设计如此）

## 总体进度

| 阶段 | 状态 | 说明 |
|---|---|---|
| P0 生产基线 | ✅ 100% | PostgreSQL、worker/outbox、鉴权、API 加固、工具治理、保留清理、可观测与 CI 收尾完成 |
| P1 韧性与深度 | ✅ 100% | 五件套、Higress、HTTP mock、评测、模型网关、知识 CLI、压测/混沌/安全已完成；前端加固按决定不做；镜像 CVE 修复归入 P2 |
| P2 规模化运维 | 约 10% | Tempo 主 Trace 已接入；镜像 CVE、SLO、badcase/工单闭环未完成 |

## P0 明细

| 工作流 | 状态 | 已完成 | 剩余说明 |
|---|---|---|---|
| W0 配置/部署 | ✅ 100% | Dockerfile、Compose core、环境变量、`SecretStr` 密钥、生产鉴权/CORS/Host 校验 | — |
| W1 PostgreSQL | ✅ 100% | PostgreSQL + Alembic、仓储分层、Checkpoint、outbox、lease、SQL 边界测试 | 历史 SQLite Checkpoint 不迁移（既定非目标） |
| W2 Redis | ✅ 100% | 限流、LLM 缓存、故障降级、指标 | — |
| W3 鉴权/API | ✅ 100% | JWT/OIDC、request_id、限流、就绪探针、错误信封、CORS/TrustedHost、游标分页、SSE 心跳/超时/断连、scope 强制、任务/会话归属 | — |
| W4 Worker/Outbox | ✅ 100% | worker 分离、outbox relay、任务 lease、保留清理 worker、积压指标 | — |
| W5 模型网关 | ✅ 100% | fallback、结构化校验/修复、成本账本、缓存、超时；P1 已补真流式、共享熔断、prompt 注册表、任务预算 | — |
| W6 工具治理 | ✅ 100% | 输入/输出 schema、超时、required_scopes、错误分类、工具指标、guard/审批/下单/幂等回放审计 | — |
| W7 可观测 | ✅ 100% | OTel、JSON 日志、Prometheus 指标、Postgres trace 投影、五件套、告警规则接入共享 Prometheus | SkyWalking 原生服务目录为空，已用 Zipkin API 查询 |
| W8 测试/CI/文档 | ✅ 100% | 138 tests、83.8% 覆盖率、PG 测试库、ruff、mypy（新模块）、GitHub Actions 实际运行通过、ADR、Runbook | — |

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
- 告警已挂载到共享 Prometheus（`/etc/prometheus/rules/itinerary-alerts.yml`），`/api/v1/rules` 可见 8 条规则。

## P1 进展

| 项目 | 状态 |
|---|---|
| 五件套可观测 | ✅ 完成：OTel Collector → SkyWalking（Zipkin API）/Langfuse，ELK，Prometheus/Grafana |
| Higress 网关 | ✅ 完成：`/chat` 等业务路径直连 API，其余走 Web；`make higress-up` 幂等配置 |
| HTTP mock 服务 + 真实适配器 | ✅ 完成：users/inventory/approval/booking；超时/重试/trace 透传/幂等回放契约测试 |
| 评测金标集 | ✅ 完成：slot/policy/retrieval/approval/prompt/badcase 六类；阈值进 CI |
| 模型网关深度 | ✅ 完成：真流式、Redis 共享熔断、prompt 版本注册表、任务预算、fallback/校验/成本 |
| 知识入库 CLI / 重建 | ✅ 完成：ingest/reindex/check；结构化入库、pg_trgm 重建、Milvus 重建、一致性审计 |
| 前端鉴权/错误边界/SSE 重连/测试 | ⏭ 按决定不做 |
| 压测/混沌/安全 | ✅ 完成：k6 20/50/100 阶梯、PG/Redis/worker/resume 混沌、Toxiproxy、安全回归、依赖/镜像扫描；CVE 修复归入 P2 |

### 范围决定：前端加固不纳入当前 P1

- 决定日期：2026-11-01
- 现有 Vue 控制台继续可用，不新增登录/路由守卫、全局错误边界、
  SSE 自动重连、Vitest/Playwright 测试。
- `web/` 下的测试依赖已安装，但本轮不接入 CI；如后续恢复前端加固，
  注意 Playwright 1.64.1 不支持 macOS 13 内置 Chromium，本地需使用
  系统 Chrome（`channel: "chrome"`），CI 使用 Linux + 自带 Chromium。

## 当前运行

- Higress 网关：8081（控制台 8002）
- HTTP mock 依赖：9003
- 项目栈：API 8000、worker 8001、Web 8080、PostgreSQL 55432、Redis 56379
- Tempo：3200（OTLP 14317 / 14318）
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

1. **SkyWalking 原生服务目录为空**：OTLP trace 按设计写入 `sw_zipkin_span-*`，不生成 `sw_segment`。已启用 `SW_QUERY_ZIPKIN`，通过 `http://127.0.0.1:19412/zipkin/api/v2/services` 查询服务/span/trace；Horizon 原生 UI 不展示 Zipkin 数据。详见 `docs/runbooks/skywalking.md`。
2. **mypy 渐进覆盖**：application/eval/knowledge/security/tools/workers/repositories 通过；orchestration/infra 容器等旧模块尚未纳入严格检查，`make typecheck` 与 CI 使用同一范围。
3. **镜像 CVE**：Trivy 扫描出 43 HIGH/CRITICAL（38 OS + 5 Python）。Python 侧可升级 msgpack/urllib3/setuptools；OS 侧需在 P2 升级基础镜像或定期重建。详见 `docs/status/security-report-2026-11-02.md`。
4. Langfuse 与业务各有一套 Postgres/Redis，这是有意的故障域隔离，不建议合并。
5. `mock-idp` 仅 JWT 调试需要，可随时停止。

## 人工验收

完整测试与观测手册：`docs/runbooks/p0-acceptance.md`

覆盖：

- 自动化基线、启动与健康检查
- seed 演示任务、审批恢复、修改/取消、反馈/badcase
- 重启保留、worker 停机、重复审批、并发 resume、审计/幂等/outbox
- 鉴权、跨租户、JWT、限流、CORS
- PG/Redis/模型降级
- Grafana/Prometheus/Kibana/Langfuse/SkyWalking/OTel Collector 观察方法

## 验证命令

```bash
make lint
make typecheck
make eval
TEST_DATABASE_URL=postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary_test make test
cd web && npm run build
```

本轮结果：

- `ruff check src tests`：通过
- `mypy`（CI 范围，含 eval/knowledge）：通过
- `pytest`：138 passed，83.8% 覆盖率
- `make eval`：全部 suite 通过
- Prometheus：8 条告警规则已加载

## 评测金标集（P1）

`make eval` 输出：

| suite | 用例 | 指标 |
|---|---|---|
| slot | 16 | exact=1.0，field=1.0 |
| policy | 16 | accuracy=1.0 |
| retrieval | 10 | recall@5=1.0，MRR=0.95，citation precision=0.81，insufficient=1.0 |
| approval | 14 | pass=1.0 |
| prompt | 6 | v1/v2 准确率=1.0 |
| badcase | 4 | replay=1.0 |

- 评测 runner 在 `src/itinerary_agent/eval/`
- 用例与阈值在 `tests/eval/`
- `pytest` 和 CI 都执行同一套阈值

## P2 进展

| 项目 | 状态 |
|---|---|
| Tempo 主 Trace 后端 | ✅ 接入；Collector 双写 Tempo + SkyWalking |
| 日志结构化 | ❌ 未开始 |
| 业务 KPI 导出 | ❌ 未开始 |
| SLO/燃烧率告警 | ❌ 未开始 |
| Badcase 自动导出 / 工单 | ❌ 未开始 |
| 数据集版本化/拆分 | ❌ 未开始 |
| 镜像 CVE 修复 | ❌ 未开始 |

## 模型网关深度（P1）

- 真流式：`OpenAIChatGateway.stream` + LangGraph custom stream + SSE `token` 事件
- 首 token 前允许 fallback，首 token 后不再切换，避免拼接两个模型的半截回答
- Redis 共享熔断：closed/open/half_open，冷却后单试探；Redis 故障 fail-open
- Prompt 注册表：understand v1/v2、plan v1、summarize v1；版本写入 `llm_calls`
- 任务级 token/成本预算（0 表示不限制）
- 新增指标与 `ItineraryModelCircuitOpen` 告警
- Runbook：`docs/runbooks/model-gateway.md`

## 知识 CLI（P1）

- `knowledge-ingest`：结构化制度 JSON → PostgreSQL 条款/边/表格，可选 Milvus
- `knowledge-reindex`：重建 pg_trgm 索引 + 重新生成 Milvus 向量
- `knowledge-check`：父节点、引用/例外边、表格、重复 path、待校对引用
- 无 Milvus 时使用 `--skip-vectors`；无 DashScope Key 时使用确定性 hash embedding
- Runbook：`docs/runbooks/knowledge.md`
- 已用 demo fixture 实测 ingest/check/reindex 通过

## 压测/混沌/安全（P1）

- k6 脚本：`load/k6/{smoke,chat,mixed}.js`，`make load-*`
- Toxiproxy profile：`make chaos-up`，`scripts/chaos/toxiproxy.sh`
- 混沌脚本：`scripts/chaos/run.sh {pg,redis,worker,concurrent-resume}`
- 安全回归：`tests/test_security.py` 4 条
- 已通过：PG/Redis 降级、worker 停机恢复、并发 resume、Toxiproxy 延迟注入
- k6 阶梯已完成：只读 100 VU 263.7 RPS / P95 207ms；chat 100 VU 26.8 RPS / P95 3.1s，0 错误
- 报告：`docs/status/load-report-2026-11-01.md`
- Runbook：`docs/runbooks/load-chaos-security.md`

## 依赖与镜像安全

- `make audit`：Python / 前端 / 镜像统一扫描入口
- 前端生产依赖：0 vulnerabilities
- 前端全部依赖：7 moderate，全部在 dev 依赖链
- Python：待安装 `pip-audit`
- 镜像：待安装 `trivy` 或登录 Docker Scout
- 报告：`docs/status/security-report-2026-11-02.md`

## CI

- `make ci` = lint + typecheck + test + eval
- GitHub Actions 已实际运行通过：
  https://github.com/tiamo-zl/Itinerary_reservation_agent/actions/runs/41388031769
- 后端 job：lint / mypy / migrate / pytest / eval 全部通过
- 前端 job：构建通过
- Runbook：`docs/runbooks/ci.md`

## 建议下一步（P1）

1. 修复镜像 Python 包 CVE（msgpack / urllib3 / setuptools），重建镜像。
2. P2：升级基础镜像/定期重建，降低 Debian OS CVE。
3. P2：备份/恢复演练、SLO/告警、PgBouncer、多副本。
