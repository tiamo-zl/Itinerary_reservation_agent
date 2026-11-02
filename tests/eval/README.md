# 评测金标集

离线、确定性、可在 CI 中运行的评测集。不调用真实模型或网络。

## 运行

```bash
make eval
# 或
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli
```

默认只跑 `golden + regression`，`holdout` 不参与常规门禁：

```bash
make eval-holdout
# 或
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --split holdout
```

只跑某个 suite：

```bash
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --suite retrieval
```

数据集版本在 `tests/eval/dataset.json`。每条结果会记录
`dataset_version` 和 `split`。

输出 JSON（CI 归档）：

```bash
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --json
```

阈值未通过时进程返回 1；`--no-enforce` 只报告不失败。

## 目录

```text
tests/eval/
  cases/
    slot_cases.jsonl        # 需求理解：别名、相对日期、默认槽位
    policy_cases.jsonl      # 差标：职级/城市/生效日期/默认回退/审批
    retrieval_cases.jsonl   # RAG：关键词、语义、引用、例外、父子、表格、不足
    retrieval_kb.json       # 检索评测共享条款树/边/表格
    approval_cases.jsonl    # guard 准入与 revision 修改
    prompt_cases.jsonl      # 按 prompt_version 分组的记录输出 A/B
    badcase_cases.jsonl     # badcase 回放（内嵌 case，默认 regression）
    scenario_cases.jsonl    # 12 个端到端场景清单
  dataset.json              # 数据集版本与默认 split
  thresholds.json           # CI 阈值
```

每个 case 可以显式写 `"split": "golden|regression|holdout"`；
未写时按 `dataset.json` 的 `default_split` 注入。
badcase wrapper 由导出 CLI 自动标记为 `regression`。

## 指标

| suite | 指标 |
|---|---|
| slot | `exact_match_rate`、`field_accuracy` |
| policy | `decision_accuracy`（passed + requires_approval） |
| retrieval | `recall_at_5`、`mrr`（种子排序）、`citation_precision`、`insufficient_accuracy` |
| approval | `scenario_pass_rate` |
| prompt | 每个版本的 `*_exact_match_rate` 与整体准确率 |
| badcase | `replay_pass_rate` |

## 用例格式

### slot

```json
{"id":"...","today":"2026-10-21","raw":{"destination":"北京","departure_date":"下周二"},"expected":{"destination_city":"北京","start_weekday":1}}
```

`start_weekday`（0=周一）和 `duration_days`（end-start 天数）是派生断言。

### policy

```json
{"id":"...","level":"L2","destination_city":"北京","hotels":[{"price":800}],"rules":[{"id":"h-l2","match":{"employee_level":["L2"]},"category":"hotel","limit":500,"severity":"block","allow_approval":true}],"expected_passed":false,"expected_requires_approval":true}
```

### retrieval

```json
{"id":"...","query":"住宿标准","dense_ids":["c1"],"filters":{"employee_level":"L2","city_tier":1},"expected":["c1","c2"],"expected_insufficient":false}
```

`dense_ids` 模拟向量召回；关键词召回由 `MemoryPolicyStore` 对共享 KB 做子串匹配。
`expected_table_rows` 可选，用于断言表格行过滤。

### approval

guard 用例：

```json
{"id":"...","action":"book_hotel","status":"EXECUTING","policy_passed":false,"requires_approval":true,"approval_status":"pending","confirmed":true,"expected_code":"APPROVAL_REQUIRED"}
```

revision 用例：

```json
{"id":"...","kind":"amendment","revision":0,"amended_request":{"destination_city":"上海"},"expected_revision":1}
```

### prompt

按 `prompt_version` 分组评估记录下来的模型输出，对比不同 prompt 版本：

```json
{"id":"...","prompt_version":"v1","today":"2026-10-21","raw_output":"{\"destination\":\"上海\",...}","expected":{"destination_city":"上海",...}}
```

### badcase

```json
{"id":"...","suite":"slot","case":{ ...与对应 suite 相同的 case... }}
```

应用侧从 `badcases` 表导出后，按 suite 组装成该格式即可回放。

## 阈值

`thresholds.json` 中的每个键对应 suite 指标；低于阈值时 `make eval` 返回 1。
当前 CI 在 `pytest` 之后执行同一 runner。
