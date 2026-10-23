# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目现状

这是差旅预订 Agent 的**生产级形态学习 demo**：架构与工程机制按生产标准设计，本地运行，外部系统全部 mock。

当前进度：

- **M0 已完成**：依赖与配置、共享领域模型、SQLite schema、Trace 基础设施、FastAPI 应用与 `/health`。
- **下一步 M1**：接入网关、LangGraph 编排主链路（脚本化模型）。
- 暂无真实外部系统接入；DeepSeek / DashScope / Milvus 在 M3 才真正使用。

两份权威文档：

- 设计：`docs/superpowers/specs/2026-10-21-itinerary-agent-design.md`
- 实现计划：`docs/superpowers/plans/2026-10-21-itinerary-agent-implementation.md`

动手前先读设计文档的对应章节和计划里的当前任务，不要凭记忆猜接口。

## 常用命令

```bash
uv sync --dev                     # 安装运行与开发依赖
uv run pytest -q                  # 全量测试
uv run pytest tests/test_db.py -v # 单文件
uv run pytest tests/test_db.py::test_init_and_insert_task -v  # 单测试
uv run ruff check src tests       # lint
uv run uvicorn itinerary_agent.main:app --reload
```

依赖由用户安装：不要自行执行 `uv add`、`uv sync` 或下载中间件。需要新依赖时先说明用途并等待用户安装。

## 架构

单个 Python 进程，七个逻辑层分包在 `src/itinerary_agent/`：

```text
api/            L1 接入网关
orchestration/  L2 LangGraph 编排与 Checkpoint
tools/          L3 工具注册、风险分级、执行
knowledge/      L4 制度条款树、引用图、混合检索、记忆
model_gateway/  L5 聊天与 embedding 唯一出口
control/        L6 差标求值、动作准入、审批闸门
observability/  L7 trace/span 与回放
domain/         共享领域模型
adapters/       外部系统接口 + mock 实现
infra/          配置、SQLite、组合根
```

必须保持的约束：

- `api` 只知道 `Orchestrator` 接口，不 import LangGraph。
- 所有模型/embedding 调用只经过 `model_gateway`；所有外部业务系统只经过 `tools`。
- 编排状态只存摘要与引用 ID，不存制度原文、聊天全文或完整库存。
- 差标判定由 `control` 的确定性规则完成；RAG 只负责解释和引用。
- `infra` 是唯一允许出现具体实现/mock 的装配位置。

制度检索不是章节切分：使用条款树、引用/例外边、结构化表格，检索时混合召回 + 图扩展，返回带 citations 的 `PolicyContext`。

## 当前代码约定

- 所有 I/O 为 async；SQLite 使用 `aiosqlite`。
- LangGraph 状态存 JSON 可序列化的 dict，节点边界用 Pydantic `model_validate` 转换。
- 时间使用 `datetime.now(UTC)`，入库为 ISO 字符串。
- Trace 写入失败只记日志，不影响业务。
- 测试默认使用临时 SQLite 和脚本化模型，不访问真实网络。

## 环境注意事项

- Python 3.13 + uv；`.venv` 由 uv 管理。
- `pymupdf` 固定为 `<2.0`：2.0 会引入 `pymupdf-layout` → `onnxruntime`，后者没有 Intel macOS x86_64 wheel。
- `pymilvus` 固定为 `<3.0`，保持 2.x `MilvusClient` API。
- Milvus 使用本地已有服务：`127.0.0.1:19530`。
- 外部系统（用户、权限、角色、库存、审批、下单、制度文档）均为 mock。

## 业务背景

员工用自然语言提出差旅需求（如“下周二去北京出差两天，住在王府井附近，1000 元以内”），Agent 串联需求理解、行程规划、机票/酒店查询、差标校验、审批与下单。核心分支包括中途改预算/目的地、审批驳回、人在回路确认和检索降级。
