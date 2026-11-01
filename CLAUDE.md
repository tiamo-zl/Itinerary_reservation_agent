# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目现状

这是差旅预订 Agent 的**生产级形态学习 demo**：架构与工程机制按生产标准设计，本地运行，外部系统全部 mock。

当前进度：

- **M0–M5 已完成**：七层骨架、网关与编排、工具/库存、模型网关与制度检索、差标/审批/下单、Trace 与 12 个端到端场景。
- **P0 生产化基线已完成**：PostgreSQL + Alembic、API/worker 分离、outbox + 任务 lease、JWT/OIDC、Redis 限流与缓存、模型主备切换、结构化日志/指标/OTel 接入点、Docker Compose 与 CI。
- **观测控制台**：`web/`（Vue 3 + Vite）提供聊天、对话记录、审批工作台、流转图、trace 回放、线上概览；后端提供 trace 列表/概览、流转图、Checkpoint 历史、反馈与 badcase 回流。
- **评测集 harness**：`tests/eval/`，JSONL 用例覆盖槽位、差标和场景清单。
- 默认 `MODEL_MODE=scripted`、`ADAPTER_MODE=mock`、`AUTH_MODE=mock`，完全离线可运行。
- live 模式已用 DeepSeek + DashScope + 本地 Milvus 完成主链路、审批与修改需求联调。

两份权威文档：

- 设计：`docs/superpowers/specs/2026-10-21-itinerary-agent-design.md`
- 实现计划：`docs/superpowers/plans/2026-10-21-itinerary-agent-implementation.md`

动手前先读设计文档的对应章节和计划里的当前任务，不要凭记忆猜接口。

## 常用命令

```bash
uv sync --dev                     # 安装运行与开发依赖
make db-up                        # PostgreSQL 55432 / Redis 56379
make migrate                      # Alembic upgrade head
make api                          # API http://127.0.0.1:8000
make worker                       # Worker http://127.0.0.1:8001
make higress-up                   # 接入本机 Higress 网关（入口 8081）
make test                         # 全量测试，需要 TEST_DATABASE_URL
make eval                         # 金标集 + CI 阈值
make knowledge-check              # 制度数据一致性
make lint                         # ruff
make typecheck                    # mypy（新模块）

cd web && npm install              # 前端依赖由用户安装
cd web && npm run dev              # Vue 控制台 http://127.0.0.1:5211
cd web && npm run build            # 类型检查 + 构建

docker compose --profile core up -d --build   # Web 8080 + API/worker + PG/Redis
```

依赖由用户安装：不要自行执行 `uv add`、`uv sync` 或下载中间件。需要新依赖时先说明用途并等待用户安装。

## 架构

单个 Python 进程，七个逻辑层分包在 `src/itinerary_agent/`：

```text
api/                   L1 接入网关（Controller）
application/           用例服务、权限、事务边界
orchestration/         L2 LangGraph 编排与 Checkpoint
tools/                 L3 工具注册、风险分级、执行
knowledge/             L4 制度条款树、引用图、混合检索、记忆
model_gateway/         L5 聊天与 embedding 唯一出口
control/               L6 差标求值、动作准入、审批闸门
observability/         L7 trace/span、日志、指标、OTel
domain/                共享领域模型
adapters/              外部系统接口 + mock 实现
infra/                 配置、PostgreSQL、组合根
infra/repositories/    唯一允许写 SQL 的仓储层
workers/               outbox relay、审批轮询、保留清理
```

必须保持的约束：

- `api` 只知道 `Orchestrator` 接口，不 import LangGraph；不直接访问数据库。
- 所有模型/embedding 调用只经过 `model_gateway`；所有外部业务系统只经过 `tools`。
- 编排状态只存摘要与引用 ID，不存制度原文、聊天全文或完整库存。
- 差标判定由 `control` 的确定性规则完成；RAG 只负责解释和引用。
- `infra` 是唯一允许出现具体实现/mock 的装配位置。
- SQL 只允许出现在 `infra/repositories/`（连接层与迁移除外），由边界测试强制。
- API 进程无状态；审批恢复、outbox、保留清理由 worker 负责。
- 生产环境禁止 `AUTH_MODE=mock`；JWT/OIDC 在最外层中间件完成认证。

制度检索不是章节切分：使用条款树、引用/例外边、结构化表格，检索时混合召回 + 图扩展，返回带 citations 的 `PolicyContext`。

## 当前代码约定

- 所有 I/O 为 async；业务数据使用 PostgreSQL + psycopg 3 连接池。
- 仓储使用 `Database.execute/fetchone/fetchall`；需要原子性时用 `db.transaction()`。
- LangGraph 状态存 JSON 可序列化的 dict，节点边界用 Pydantic `model_validate` 转换。
- 时间使用 `datetime.now(UTC)`，数据库列为 `timestamptz`。
- Trace 写入失败只记日志，不影响业务；OTel、Prometheus、ELK 都是可选的。
- 测试使用共享 PostgreSQL 测试库（`TEST_DATABASE_URL`）和脚本化模型，不访问真实网络。
- 恢复任务前必须获取任务 lease；审批决定与 outbox 事件同事务写入。

## 环境注意事项

- Python 3.13 + uv；`.venv` 由 uv 管理。
- 前端 Node 24 + npm；前端依赖由用户安装，不要自行执行 `npm install`。
- `pymupdf` 固定为 `<2.0`：2.0 会引入 `pymupdf-layout` → `onnxruntime`，后者没有 Intel macOS x86_64 wheel。
- `pymilvus` 固定为 `<3.0`，保持 2.x `MilvusClient` API。
- Milvus 使用本地已有服务：`127.0.0.1:19530`。
- 本地 Compose 的 PostgreSQL 使用 `55432`、Redis 使用 `56379`，避开已有 Langfuse 栈的 5432/6379。
- 测试需要 `itinerary_test` 数据库；`make db-up` 首次初始化会自动创建。
- LangGraph checkpoint 表由 `langgraph-checkpoint-postgres` 管理，不用 Alembic 手改。
- 外部系统（用户、权限、角色、库存、审批、下单、制度文档）均为 mock。

## 业务背景

员工用自然语言提出差旅需求（如“下周二去北京出差两天，住在王府井附近，1000 元以内”），Agent 串联需求理解、行程规划、机票/酒店查询、差标校验、审批与下单。核心分支包括中途改预算/目的地、审批驳回、人在回路确认和检索降级。
