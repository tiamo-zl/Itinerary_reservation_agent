# Runbook: Badcase → 工单 → 回归用例 → CI 闭环

## 目标

```text
反馈 → 工单 → 归因 → 结构化回归用例 → 导出
→ CI 失败（复现）→ 修复 → CI 通过 → 关闭
```

## 1. 创建

```bash
curl -s -X POST http://127.0.0.1:8081/feedback \
  -H 'X-Mock-User: u001' \
  -H 'Content-Type: application/json' \
  -d '{
    "trace_id":"<TRACE_ID>",
    "task_id":"<TASK_ID>",
    "category":"policy",
    "severity":"high",
    "user_input":"L2 住 800 的酒店",
    "expected":"应要求审批",
    "actual":"直接通过"
  }'
```

返回：

```json
{
  "badcase_id": "...",
  "status": "open",
  "ticket_ref": "LOCAL-...",
  "sla_due_at": "2026-11-03T..."
}
```

- `ticket_ref` 目前由本地 demo 适配器生成
- SLA：high 1 天、medium 7 天、low 14 天
- 后续可替换为 Gitee/GitHub Issues/Jira 适配器

## 2. Triage

管理员通过 PATCH 推进：

```bash
curl -s -X PATCH http://127.0.0.1:8081/badcases/<BAD_CASE_ID> \
  -H 'X-Mock-User: u002' \
  -H 'Content-Type: application/json' \
  -d '{
    "status":"fixed",
    "owner":"u002",
    "root_cause":"policy rule limit 配错",
    "regression_suite":"policy",
    "regression_case":{
      "id":"replay-policy-l2-hotel-800",
      "level":"L2",
      "destination_city":"北京",
      "hotels":[{"price":800}],
      "rules":[{"id":"h-l2","match":{"employee_level":["L2"]},"category":"hotel","limit":500,"severity":"block","allow_approval":true}],
      "expected_passed":false,
      "expected_requires_approval":true
    }
  }'
```

允许的 `regression_suite`：

```text
slot / policy / retrieval / approval / prompt
```

## 3. 关闭约束

```bash
curl -s -X PATCH http://127.0.0.1:8081/badcases/<ID> \
  -H 'X-Mock-User: u002' \
  -H 'Content-Type: application/json' \
  -d '{"status":"closed"}'
```

如果没有 `regression_suite` / `regression_case`，返回 400：

```json
{
  "error": "closing a badcase requires regression_suite and regression_case",
  "code": "BAD_REQUEST"
}
```

这是“没有回归用例不允许关单”的硬约束。

## 4. 导出回归用例

```bash
make badcase-export ARGS="--merge tests/eval/cases/badcase_cases.jsonl"
```

- 只导出有 `regression_suite` + `regression_case` 的 badcase
- `--merge` 按 `id` 合并，保留手工用例
- 每条 wrapper 带 `source_trace_id`

输出格式：

```json
{"id":"badcase-<id>","suite":"policy","split":"regression","source_trace_id":"...","case":{...}}
```

## 5. CI 门禁

```bash
make eval
```

`badcase` suite 阈值是 `1.0`：

- 用例未修复前 CI 会红
- 修复后全绿才能关闭工单
- GitHub Actions 会执行同一套 runner

## 6. 指标

- `itinerary_badcases{status}`：open/reproduced/fixed/closed 数量
- `itinerary_badcase_rate_per_1000_tasks`
- Grafana `Itinerary Business Funnel`

## 7. 替换真实工单系统

实现 `application.ports.TicketPort`：

```python
class TicketPort(Protocol):
    async def create(self, badcase: dict) -> str: ...
    async def close(self, ticket_ref: str, comment: str) -> None: ...
```

当前 `infra/ticketing.py` 的 `LocalTicketAdapter` 只生成本地编号。
生产可替换为：

- Gitee Issues
- GitHub Issues
- Jira
- Linear

建议工单正文自动带：

```text
trace_id / task_id / category / severity / expected / actual
```

## 8. 当前边界

- 自动导出的是已 triage 的结构化用例，不是从自然语言自动生成用例；
- 关单前仍需要人工写 `regression_case`；
- 外部工单同步尚未接入，当前是本地 demo 适配器。
