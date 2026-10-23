# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 先读什么

- 设计：`docs/superpowers/specs/2026-10-21-itinerary-agent-design.md`
- 实现计划：`docs/superpowers/plans/2026-10-21-itinerary-agent-implementation.md`
- Claude 的完整工作说明：`CLAUDE.md`（架构约束与约定以它和设计文档为准）

## 项目现状

差旅预订 Agent 的生产级形态学习 demo，本地运行、外部系统全部 mock。

- **M0–M5 已完成**：七层骨架、编排、工具、制度检索、差标/审批/下单、Trace 和 12 个场景。
- 默认 scripted + mock，完全离线可运行。
- live 模式已装配，但尚未用真实 Key 与 Milvus 做完整联调。

## 命令

```bash
uv sync --dev
uv run pytest -q
uv run pytest tests/test_db.py::test_init_and_insert_task -v
uv run ruff check src tests
uv run uvicorn itinerary_agent.main:app --reload
```

依赖与中间件由用户安装；不要自行执行 `uv add`、`uv sync` 或下载组件。

## 关键约束

- 七层逻辑分包，依赖单向；具体实现只在 `infra` 装配。
- 模型/embedding 只走 `model_gateway`；外部业务系统只走 `tools`。
- 编排状态只放摘要与引用 ID；制度原文和聊天全文不进状态。
- 差标由 `control` 规则确定性判定；RAG 只解释与引用。
- 制度检索使用条款树 + 引用/例外图 + 结构化表格，不做章节切分。

## 环境注意

- `pymupdf<2.0`：2.0 会经 `pymupdf-layout` 引入 `onnxruntime`，Intel macOS 无可用 wheel。
- `pymilvus<3.0`：保持 2.x `MilvusClient` API。
- Milvus 地址：`127.0.0.1:19530`。
- 测试默认临时 SQLite + 脚本化模型，不访问真实网络。
