# Runbook: 模拟工单提交页

## 定位

这是 badcase 的**模拟工单入口**，不是真实工单系统：

```text
/tickets 页面
  → POST /feedback
  → FeedbackService
  → LocalTicketAdapter
  → ticket_ref = LOCAL-xxxxxxxx
  → badcases 表（status=open）
```

它独立于已冻结的 Vue 观测控制台，属于质量运营/business state 的
临时入口。以后接 Gitee / GitHub Issues / Jira 时，页面可以保留，
只替换后端 `TicketPort`。

## 访问

- Higress：<http://127.0.0.1:8081/tickets>
- API 直连：<http://127.0.0.1:8000/tickets>
- Web Nginx（重建 web 镜像后）：<http://127.0.0.1:8080/tickets>

本地使用 mock 身份：

- 提交：`X-Mock-User: u001`（`feedback:write`）
- 最近工单列表：`X-Mock-User: u002`（管理员/审批人，`badcase:manage`）

生产必须改成 JWT/OIDC；页面的 mock header 只用于本地演示。

## 表单字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `trace_id` | 是 | 从聊天响应或 `/traces` 获取；用于关联链路 |
| `task_id` | 否 | 任务 ID |
| `category` | 是 | understand / plan / tool / policy / rag / approval / booking / other |
| `severity` | 是 | low / medium / high |
| `user_input` | 否 | 用户原始需求 |
| `expected` | 否 | 期望结果 |
| `actual` | 否 | 实际结果 |
| `comment` | 否 | 备注 |

提交后展示：

```text
工单已进入模拟队列
ticket_ref: LOCAL-xxxxxxxx
badcase_id: ...
status: open
sla_due_at: ...
```

SLA 规则：

| severity | SLA |
|---|---|
| high | 1 天 |
| medium | 7 天 |
| low | 14 天 |

## 后续处理

管理员通过 API 推进：

```bash
# 列表
curl -s 'http://127.0.0.1:8081/badcases?limit=20' \
  -H 'X-Mock-User: u002'

# 标记 fixed，并写入回归用例
curl -s -X PATCH 'http://127.0.0.1:8081/badcases/<badcase_id>' \
  -H 'Content-Type: application/json' \
  -H 'X-Mock-User: u002' \
  -d '{
    "status": "fixed",
    "regression_suite": "policy",
    "regression_case": {"id": "replay-..."}
  }'
```

关闭约束：`status=closed` 前必须有 `regression_suite` 和
`regression_case`。关闭时会调用 `TicketPort.close`，本地适配器是空操作。

导出回归用例：

```bash
make badcase-export
```

详见 `docs/runbooks/badcase-loop.md`。

## 以后接真实工单

保持页面和 `/feedback` API 不变，只替换 `TicketPort`：

```text
TicketPort.create(badcase) -> issue 编号/URL
TicketPort.close(ticket_ref, comment) -> 评论 + 关闭 issue
```

可选适配器：

- Gitee Issues（仓库已在 Gitee，国内访问方便）
- GitHub Issues
- Jira / ServiceNow

注意事项：

- 不要往 issue 正文写完整 PII；使用 `trace_id` / `badcase_id` 关联；
- 需要 token、repo/project、label/priority、assignee 映射；
- 创建要幂等（按 badcase_id 查重）；
- 关闭失败只记日志，不阻断业务；
- 如需 issue 状态回写，增加 webhook 或轮询。

## 测试

```bash
TEST_DATABASE_URL=postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary_test \
  uv run pytest -q tests/test_ticket_page.py
```
