# 生产化改造进度（2026-11-01）

- 分支：`feat/observability-console`
- 最新基线：`dd11caf refactor: reuse the shared monitoring stack`
- 测试：**102 passed**，覆盖率约 **85%**
- 默认运行模式：`MODEL_MODE=scripted`、`ADAPTER_MODE=mock`、`AUTH_MODE=mock`

## 总体进度

| 阶段 | 状态 | 说明 |
|---|---|---|
| P0 生产基线 | 约 85% | 核心出口条件已满足；工具治理和部分 API 加固未收尾 |
| P1 韧性与深度 | 约 20% | 只完成五件套可观测；评测、HTTP mock、前端、压测未开始 |
| P2 规模化运维 | 0% | 未开始 |

## P0 明细

| 工作流 | 状态 | 已完成 | 缺口 |
|---|---|---|---|
| W0 配置/部署 | 🟡 80% | Dockerfile、Compose core、Makefile、环境变量、生产鉴权校验 | 密钥未全部 `SecretStr`；CORS/trusted hosts 生产校验 |
| W1 PostgreSQL | ✅ 100% | PostgreSQL + Alembic、仓储分层、Postgres Checkpoint、outbox、lease、SQL 边界测试 | 历史 SQLite checkpoint 不迁移（既定非目标） |
| W2 Redis | ✅ 100% | 限流、LLM 缓存、故障降级、指标 | — |
| W3 鉴权/API | 🟡 70% | JWT/OIDC、中间件、request_id、限流、就绪探针、错误信封 | CORS、游标分页、SSE heartbeat/断连、scopes 强制、session messages 归属校验 |
| W4 Worker/Outbox | 🟡 85% | worker 分离、outbox relay、lease、重复恢复保护 | retention 清理任务 |
| W5 模型网关 | ✅ 90% | fallback、结构化校验/修复、成本账本、缓存、超时 | 真流式、共享熔断、prompt 注册表属于 P1 |
| W6 工具治理 | ❌ 45% | 输入 schema、guard、基础审计、mock 幂等 | 输出 schema、超时、required_scopes、错误分类、写操作审计覆盖 |
| W7 可观测 | ✅ 90% | OTel、JSON 日志、Prometheus 指标、Postgres trace 投影、五件套 | 告警规则未接入现有 Prometheus；SkyWalking 服务目录查询为空 |
| W8 测试/CI/文档 | ✅ 85% | 102 tests、85% 覆盖率、PG 测试库、ruff、CI、ADR、Runbook | mypy 仅覆盖新模块；CI 未在 GitHub 实际运行 |

## P1 明细

| 项目 | 状态 |
|---|---|
| 五件套可观测 | ✅ 基本完成：OTel Collector → SkyWalking/Langfuse，ELK，Prometheus/Grafana |
| 模型网关深度 | 🟡 部分：fallback/校验/成本已完成；真流式、熔断、prompt 版本未做 |
| 评测金标集 | ❌ 未开始 |
| 独立 HTTP mock 服务 + 契约测试 | ❌ 未开始 |
| 知识入库 CLI / 重建 | ❌ 未开始 |
| 前端鉴权/错误边界/SSE 重连/测试 | ❌ 未开始 |
| 压测/混沌/安全 | ❌ 未开始 |

## 本轮完成的关键能力

- PostgreSQL 业务库 + Alembic + Postgres Checkpoint
- Controller → Application Service → Repository 分层；SQL 边界测试
- API / worker 分离；审批 outbox + 任务 lease
- JWT/OIDC 鉴权与本地 mock IdP
- Redis 限流与 LLM 缓存
- 模型主备切换、结构化校验/修复、成本账本
- JSON 日志、Prometheus 指标、OTel 接入
- Dockerfile、Compose core、GitHub Actions CI
- 五件套：OTel Collector、SkyWalking、Langfuse、Prometheus/Grafana、ELK

## 当前运行

- 项目栈：API 8000、worker 8001、Web 8080、PostgreSQL 55432、Redis 56379
- OTel Collector：4317 / 4318 / 8889
- Prometheus：19090
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
  langfuse-stack/
```

- Langfuse compose 由现有容器反推生成，包含密钥，权限 `600`
- Named volumes 仍由 Docker 管理，不迁移到 `data/`
- 项目自身的 `Dockerfile`、`compose.yaml`、`deploy/otel`、`docker/postgres/init` 保留在仓库
- Higress 的 `/Users/lll/higress` 未迁移

## 已知问题

1. SkyWalking 原始 span 已写入 ES（`sw_zipkin_span` 6500+），但 `getAllServices` 服务目录查询为空。
2. 告警规则尚未接入现有 Prometheus。
3. Grafana 看板已放入 provisioning，但未用管理员账号做页面验证。
4. Langfuse 与业务各有一套 Postgres/Redis，这是有意的故障域隔离，不建议合并。
5. `mock-idp` 仅 JWT 调试需要，可随时停止。

## 建议下一步

1. **W6 工具治理**：输出 schema、工具超时、required_scopes、错误分类、审批/下单/guard 审计。
2. **W3 API 收尾**：CORS/trusted hosts、游标分页、SSE heartbeat/断连、session messages 归属、scope 强制。
3. **可观测补口**：告警规则接入 Prometheus；修 SkyWalking 服务目录。
4. 进入 P1：评测金标集、独立 HTTP mock 服务、知识 CLI、前端加固、压测/混沌/安全。
