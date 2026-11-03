# 50 条扩展评测集

这是一个**独立数据集**，不影响现有 `tests/eval/cases/` 和 CI 门禁。

## 运行

```bash
make eval-expansion
```

等价于：

```bash
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli \
  --cases-dir tests/eval/expansion_50/cases \
  --thresholds tests/eval/expansion_50/thresholds.json
```

当前结果：

```text
slot       15/15
policy     10/10
retrieval   8/8
approval    8/8
prompt      5/5
badcase     4/4
```

## 分布

| 文件 | 条数 | 测什么 |
|---|---:|---|
| `slot_cases.jsonl` | 15 | 目的地、日期、预算、区域、舱位、机票/酒店开关 |
| `policy_cases.jsonl` | 10 | 差标通过/审批/阻断、warn、默认规则、城市等级 |
| `retrieval_cases.jsonl` | 8 | 关键词、语义、引用扩展、例外、父章节、表格、insufficient |
| `approval_cases.jsonl` | 8 | guard 准入、审批、确认、终态、revision |
| `prompt_cases.jsonl` | 5 | v1/v2 输出归一化、相对日期、代码块、need flags |
| `badcase_cases.jsonl` | 4 | 其他 suite 的回归回放 |

## 如何合并到主评测集

把需要保留的用例追加到对应文件：

```bash
cat tests/eval/expansion_50/cases/slot_cases.jsonl \
  >> tests/eval/cases/slot_cases.jsonl
```

其他 suite 同理。合并后建议：

1. 更新 `tests/eval/dataset.json` 的 `version`，例如 `2026.11.03`；
2. 确认新用例没有 ID 重复；
3. 运行 `make eval`；
4. 如果某些用例只用于最终验收，给它们加 `"split": "holdout"`，用 `make eval-holdout` 单独跑，不要用于调参。

## 用例格式

### slot

```json
{
  "id": "slot-exp-...",
  "today": "2026-10-21",
  "raw": {
    "destination": "北京",
    "departure_date": "下周二",
    "duration_days": 2,
    "budget": 1500
  },
  "expected": {
    "destination_city": "北京",
    "start_date": "2026-10-27",
    "end_date": "2026-10-28",
    "budget_limit": 1500,
    "need_flight": true,
    "need_hotel": true
  }
}
```

也支持 `expected` 用 `start_weekday`、`duration_days` 表达，避免写死日期。

### policy

```json
{
  "id": "exp-policy-...",
  "level": "L2",
  "destination_city": "北京",
  "hotels": [{"price": 550}],
  "rules": [{
    "id": "h-l2",
    "match": {"employee_level": ["L2"]},
    "category": "hotel",
    "limit": 500,
    "severity": "block",
    "allow_approval": true
  }],
  "expected_passed": false,
  "expected_requires_approval": true
}
```

### retrieval

```json
{
  "id": "exp-retrieval-...",
  "category": "semantic",
  "query": "员工住酒店报销上限",
  "dense_ids": ["c1"],
  "expected": ["c1", "c2", "c4"],
  "expected_insufficient": false
}
```

表格过滤用例可加：

```json
"filters": {"employee_level": "L2", "city_tier": 1},
"expected_table_rows": [{"职级": "L2", "城市": "北京", "上限": 500}]
```

`retrieval_kb.json` 是本数据集的知识库；新增 clause 时同步维护。

### approval

```json
{
  "id": "exp-approval-...",
  "action": "book_hotel",
  "status": "EXECUTING",
  "policy_passed": false,
  "requires_approval": true,
  "approval_status": "pending",
  "confirmed": true,
  "expected_code": "APPROVAL_REQUIRED"
}
```

revision 用例：

```json
{
  "id": "exp-approval-amendment",
  "kind": "amendment",
  "revision": 2,
  "amended_request": {"destination_city": "上海"},
  "expected_revision": 3
}
```

### prompt

```json
{
  "id": "exp-prompt-...",
  "prompt_version": "v2",
  "today": "2026-10-21",
  "raw_output": "{\"destination_city\":\"北京\",\"start_date\":\"下周二\",\"duration_days\":2}",
  "expected": {"destination_city": "北京", "start_weekday": 1, "duration_days": 1}
}
```

### badcase

```json
{
  "id": "exp-badcase-...",
  "suite": "policy",
  "case": { "...": "对应 suite 的单条用例" }
}
```

## 阈值

`thresholds.json` 是单独副本。修改阈值时建议先只调这个文件，不影响主评测。

## Badcase 闭环

1. 在 `/trace/{trace_id}` 或 `/tickets` 提交问题；
2. 在 `/overview` 标记复现/修复；
3. 关闭前必须补 `regression_suite` + `regression_case`；
4. `make badcase-export` 导出回归用例；
5. 把导出的用例放进对应 suite，再跑 `make eval`。
