# 生产化改造进度（2026-11-01）

- 分支：`feat/observability-console`
- 最新提交：Trace 视图、离线 demo、judge 人工复核（本条提交）；上一提交：`bed4c54 feat: add simulated ticket page and judge calibration`
- 测试：**164 passed**，覆盖率 **82.0%**
- 评测：`make eval` 全部通过（66 条金标/回放用例）
- 类型检查：`make typecheck` 覆盖 application/eval/knowledge/security/tools/workers/repositories
- 默认运行模式：`MODEL_MODE=scripted`、`ADAPTER_MODE=mock`、`AUTH_MODE=mock`

## 当前快照（2026-11-03）

- 工作树：无未提交改动
- 当前运行的 API/worker：`MODEL_MODE=scripted`、`ADAPTER_MODE=mock`、`AUTH_MODE=mock`
- 运行镜像：Alpine，已包含 `/tickets` 模拟工单页、Trace Flow、judge 复核 API
- 离线 scripted 模型支持常见中文差旅表达（目的地/日期/预算/住宿区域），
  不依赖模型 Key 或 Milvus 即可演示预订、审批、确认、修改、取消
- 演示数据：
  - `p0-manual`：task `85bf6eefa5704e7b8bb886bb0ec3d17e`，trace `p0-manual-trace`，
    approval `a6dbf800114c44a7a58d374954694bcd`，状态 `WAITING_HUMAN`（已用于 worker 停机/并发 resume 混沌）
  - `p0-verify`：已走完审批 → 恢复 → 选择 → `COMPLETED`
- 观测：
  - Prometheus 8 个 target `up`（含 Alertmanager）
  - 26 条规则已加载（16 条告警 + 10 条记录规则）
  - Grafana 已 provision `Itinerary Agent`、三块生产看板与 Trace Flow
  - Tempo 主 Trace 已接入，Grafana 已加载 Tempo 数据源
  - SkyWalking Zipkin 查询 API 已启用（19412），双跑兼容
  - Horizon 原生服务目录仍为空（Zipkin 兼容数据设计如此）

## 总体进度

| 阶段 | 状态 | 说明 |
|---|---|---|
| P0 生产基线 | ✅ 100% | PostgreSQL、worker/outbox、鉴权、API 加固、工具治理、保留清理、可观测与 CI 收尾完成 |
| P1 韧性与深度 | ✅ 100% | 五件套、Higress、HTTP mock、评测、模型网关、知识 CLI、压测/混沌/安全已完成；前端加固按决定不做；镜像 CVE 修复归入 P2 |
| P2 规模化运维 | 约 95% | Tempo、日志、KPI/看板、SLO、badcase、数据集、近线评估、LLM judge、镜像 CVE、告警通知、模拟工单页、judge 校准基线、生产 Trace 视图/Service Graph/Agent 流转图已完成；控制台已冻结为 demo，正式退役暂缓 |

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
| W8 测试/CI/文档 | ✅ 100% | 164 tests、82.0% 覆盖率、PG 测试库、ruff、mypy（新模块）、GitHub Actions 实际运行通过、ADR、Runbook | — |

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
- 告警已挂载到共享 Prometheus（`/etc/prometheus/rules/itinerary-alerts.yml`），`/api/v1/rules` 可见 26 条规则（16 条告警 + 10 条记录规则）。

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

### 范围决定：控制台冻结为 demo（2026-11-02）

- 决定日期：2026-11-02
- 控制台保留可用，但不再投入：不新增功能，不为控制台单独修改数据结构。
- 不是观测/业务/质量的事实源；生产观测以 Tempo / Grafana / Kibana 为准，
  业务状态以 PostgreSQL / 后台 / 工单为准。
- runbook、告警、验收和 badcase 流程不依赖控制台。
- 当前仅绑定 `127.0.0.1:8080`；非本机部署需要认证或网关保护。
- 正式退役（删除 `/overview`、`/trace`、`/flow` 视图）暂缓，
  退出条件见 `docs/adr/0006-quality-operations-and-console-retirement.md`。

### 范围决定：工单保持模拟体验（2026-11-03）

- 不接真实 Gitee/GitHub/Jira 工单系统。
- 保留 `LocalTicketAdapter`、`/tickets` 模拟页和 `/badcases` 管理 API。
- 模拟体验覆盖：提交、ticket_ref、SLA、triage、关闭前回归用例约束。
- 真实工单后续只替换 `TicketPort`。

## 当前运行

- Higress 网关：8081（控制台 8002）
- HTTP mock 依赖：9003
- 项目栈：API 8000、worker 8001、Web 8080、PostgreSQL 55432、Redis 56379
- 模拟工单页：http://127.0.0.1:8081/tickets
- Tempo：3200（OTLP 14317 / 14318）
- Kibana 结构化日志字段：`attributes.app.*`
- Grafana 生产看板：Service Health / Agent Quality / Business Funnel / Trace Flow
- Grafana Trace Flow：Agent 节点流转图（Node Graph + 只读 PostgreSQL）
- Tempo Service Graph：service graphs / span metrics 已 remote write 到 Prometheus
- Service Health 已加入 SLO availability、1h/6h 燃烧率、审批恢复 P95
- OTel Collector：4317 / 4318 / 8889
- Prometheus：19090（已加载告警）
- Alertmanager：19093（critical/warning/info 分级邮件路由，当前使用 163 SMTP）
- Mailpit：8025（Web）/ 1025（SMTP，本地回退收件箱）
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
3. **镜像 CVE**：已改用 Alpine 运行镜像、移除运行期 pip 和无用的 SQLite 依赖；Trivy 扫描为 **0 HIGH/CRITICAL**（修复前 43）。需保留定期重建基础镜像的节奏，跟踪新 CVE。详见 `docs/status/security-report-2026-11-02.md`。
4. Langfuse 与业务各有一套 Postgres/Redis，这是有意的故障域隔离，不建议合并。
5. `mock-idp` 仅 JWT 调试需要，可随时停止。
6. 告警当前是单 Alertmanager + 邮件单渠道；按 2026-11-02 决定继续邮件，
   IM/电话暂缓。SMTP 故障时告警可能丢失。详见 `docs/runbooks/alerting.md`。
7. 控制台已冻结为 demo，不作为观测/业务/质量事实源；无完整 RBAC，
   仅绑定 `127.0.0.1:8080`。正式退役暂缓，见 ADR 0006。
8. 安全加固未做：真实 OIDC/SSO、密钥轮换、mTLS、字段级加密、审计导出
   记录为未加固（2026-11-02 决定暂不投入）。
9. Tempo Service Graph 依赖 CLIENT/SERVER span 配对；健康检查会产生
   `user → mock-deps` 虚拟边，DB/Redis 边来自 database 语义。
10. Agent 流转图来自 PostgreSQL `spans` 投影，不是 Tempo 原生
    Service Graph；只展示实际执行顺序。
11. SkyWalking 原生服务目录/拓扑仍为可选验证项，Tempo/Grafana 是主视图。

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
- `pytest`：164 passed，82.0% 覆盖率
- `make eval`：全部 suite 通过
- Prometheus：26 条规则已加载（16 条告警 + 10 条记录规则）

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
- 数据集版本：`tests/eval/dataset.json`（2026.11.02）
- 默认 CI 只跑 golden+regression；`make eval-holdout` 跑 holdout
- `pytest` 和 CI 都执行同一套阈值

## P2 进展

| 项目 | 状态 |
|---|---|
| Tempo 主 Trace 后端 | ✅ 接入；Collector 双写 Tempo + SkyWalking |
| Trace 调用树 | ✅ Grafana Explore → Tempo；按 `span.app.trace_id` 搜索 |
| Tempo Service Graph | ✅ metrics-generator + Prometheus remote write |
| Agent 流转图 | ✅ Grafana Node Graph + 只读 PostgreSQL `spans` 投影 |
| 日志结构化 | ✅ 接入；ES `attributes.app.*` 可精确查询 |
| `X-Trace-Id` | ✅ API/SSE 返回；工单与日志可用同一连接键 |
| 业务 KPI 导出 | ✅ 完成：任务/审批/badcase 状态、完成率、badcase 率、审批时延 |
| Grafana 看板 | ✅ Service Health / Agent Quality / Business Funnel / Trace Flow |
| SLO/燃烧率告警 | ✅ 99.5% SLO、10 条记录规则、5 条 SLO 告警 |
| 告警通知渠道 | ✅ Alertmanager + 163 邮件；critical/warning/info 分级路由，SMTP 25 + STARTTLS，投递已验证；授权码仅存共享栈 secret |
| Badcase 自动导出 / 工单 | ✅ 工单编号/SLA、triage 字段、关闭约束、merge 导出 |
| 模拟工单提交页 | ✅ `/tickets`：提交生成 `LOCAL-*` 工单，进入 badcase 队列；后续可替换真实 TicketPort |
| 数据集版本化/拆分 | ✅ dataset_version、golden/regression/holdout、holdout 独立运行 |
| 近线质量评估 | ✅ 抽样最近任务、确定性检查、quality_findings、指标/看板/API |
| 在线 LLM-as-judge | ✅ 抽样 COMPLETED 任务、结构化评审、judge_results、指标/看板/API（live 模式启用） |
| Judge 校准 | ✅ 24 条 seeded 数据、`make judge-calibrate`、一致率/MAE/kappa/混淆矩阵报告 |
| Judge 人工复核 | ✅ `judge_results.review_status`、PATCH API、导出/导入 CLI；人工标签入库 |
| OpenJudge align-human | ✅ 独立校准脚本、TPR/TNR/kappa/AC1/bias/calibration gate（需 ≥50 标签） |
| 在线抽样管线 | ✅ 抽样 → judge → pending 复核队列 → 人工标签 → 配对文件 → align-human |
| 镜像 CVE 修复 | ✅ Alpine 运行镜像、移除 pip 与 SQLite 死依赖；Trivy 0 HIGH/CRITICAL（修复前 43） |

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
- Python：`pip-audit` 无已知漏洞
- 镜像：Trivy **0 HIGH/CRITICAL**（修复前 43）
  - 运行镜像改为 Alpine，builder 与 runtime 一致
  - 最终镜像移除系统 pip（消除 5 个 pip vendored CVE）
  - 移除未使用的 `aiosqlite` / `langgraph-checkpoint-sqlite` / `sqlite-vec`
  - 镜像大小 554MB → 478MB
- 报告：`docs/status/security-report-2026-11-02.md`

## CI

- `make ci` = lint + typecheck + test + eval
- GitHub Actions 已实际运行通过：
  https://github.com/tiamo-zl/Itinerary_reservation_agent/actions/runs/41438354389
- 后端 job：lint / mypy / migrate / pytest / eval 全部通过
- 前端 job：构建通过
- Runbook：`docs/runbooks/ci.md`

## 下一步

待做：

1. Judge seeded 基线已跑；用人工标签复核/替换 seed，再考虑 holdout 定时跑。
2. 工单保持模拟页；需要真实工单时替换 `TicketPort`（Gitee/GitHub/Jira）。
3. 控制台正式退役（已冻结，待产品后台/工单就绪）。
4. SkyWalking 原生服务目录/拓扑（可选，Tempo/Grafana 已是主视图）。

已决定暂缓（2026-11-02）：

- 告警第二通道：继续邮件，IM/电话暂不接入。
- CI 镜像门禁、Alpine 定期重建。
- 安全加固：OIDC/SSO、密钥轮换、mTLS、字段级加密、审计导出；记录为未加固。
- 发布门禁：灰度/canary/自动回滚暂不做，先记录。
- 数据治理：PII/保留/去重/标注规范/数据集血缘/漂移监控暂不做，先记录。
