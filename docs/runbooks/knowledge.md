# Runbook: 制度入库、重建与检查

## 命令

```bash
# 导入结构化制度 JSON（默认读取配置里的租户/版本）
make knowledge-ingest ARGS="--skip-vectors"

# 重建关键词索引 + Milvus 向量
make knowledge-reindex

# 一致性检查（只读）
make knowledge-check
```

等价 CLI：

```bash
PYTHONPATH=src uv run python -m itinerary_agent.knowledge.cli \
  ingest --fixture config/policies/docs/demo-travel-policy.json
PYTHONPATH=src uv run python -m itinerary_agent.knowledge.cli reindex
PYTHONPATH=src uv run python -m itinerary_agent.knowledge.cli check --json
```

## 数据模型

一份 `PolicyBundle` 由以下部分组成：

- `clauses`：条款树（`parent_id`）、路径、标题、正文
- `refs` / `ref_texts`：已解析 ID 引用与原始引用文本
- `exceptions`：例外条款边
- `tables`：结构化表格（职级/城市/上限等）
- `policy_version`、`effective_from/to`

示例 fixture：`config/policies/docs/demo-travel-policy.json`

## ingest

流程：

1. `validate_bundle`：父节点、引用、表格必须存在；
2. 写入 `policy_clauses`；
3. 解析引用并写 `policy_edges`；解析失败的引用进入
   `policy_ingest_reviews`（重复入库不会重复建待办）；
4. 写入 `policy_tables`；
5. 生成条款向量并写入 Milvus。

选项：

| 选项 | 说明 |
|---|---|
| `--skip-vectors` | 只写 PostgreSQL，不连接 Milvus；本地无 Milvus 时使用 |
| `--embedder auto\|dashscope\|hash` | `auto` 有 DashScope Key 用真实 embedding，否则用确定性 hash |
| `--dry-run` | 只校验并输出统计 |
| `--tenant-id` / `--policy-version` | 覆盖 bundle 中的值 |

> `hash` embedding 只用于本地结构验收，不具备语义检索能力。
> 需要真实语义召回时配置 `DASHSCOPE_API_KEY` 并使用 `dashscope`。

## reindex

1. 从 PostgreSQL 读取当前租户/版本的条款；
2. 重建 `pg_trgm` 关键词索引；
3. 重新生成 clauses 的 embedding；
4. `drop_collection` + 重建 Milvus collection，批量写入。

PostgreSQL 是条款、边、表格的事实源；Milvus 只是可重建的向量索引。
`--skip-vectors` 时只重建关键词索引。

## check

只读检查：

- 父节点缺失
- 引用/例外边指向不存在的条款
- 表格缺失
- 空标题/空正文
- 重复 path
- 未知关系类型
- 待人工校对的引用

输出：

```json
{
  "ok": true,
  "errors": [],
  "warnings": [],
  "counts": {
    "clauses": 4,
    "edges": 5,
    "tables": 1,
    "pending_reviews": 0
  }
}
```

- `errors` 非空时退出码为 1；
- `--warnings-as-errors` 让 warnings 也导致失败；
- 建议在发布前和 reindex 后执行。

## 排查

### Milvus 连接失败

```text
pymilvus.exceptions.MilvusException: Fail connecting to server on 127.0.0.1:19530
```

- 本地没有 Milvus 时加 `--skip-vectors`；
- 需要向量检索时启动本地 Milvus：`127.0.0.1:19530`；
- 检查 `MILVUS_URI`、`EMBEDDING_DIMENSIONS` 是否与 collection 一致。

### check 报 dangling target

说明存储里存在指向不存在条款的边，通常来自手工 SQL 或旧版本数据：

```bash
make knowledge-check
```

先确认边是否应删除；修复后重新执行 ingest 或直接修正数据。

### pending reviews 不为 0

`ref_texts` 中的文本没有匹配到条款标题/路径/别名。处理方式：

1. 在 fixture 中补充 `aliases`；
2. 或把 `ref_texts` 改成明确的 clause_id；
3. 重新 ingest。

### reindex 后检索为空

- 确认 `--tenant-id` / `--policy-version` 与查询一致；
- 检查 Milvus collection 是否有数据；
- 关键词检索只依赖 PostgreSQL，可先用 `check` 确认条款存在。
