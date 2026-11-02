# Runbook: 业务 KPI 与三块生产看板

## 定位

业务 KPI 由 **worker** 从 PostgreSQL 定时投影到 Prometheus，API 不重复写 gauge。

- 业务事实源：PostgreSQL
- 指标入口：worker `:8001/metrics`
- 看板：Grafana `http://127.0.0.1:13000`

## 指标

| 指标 | 含义 |
|---|---|
| `itinerary_tasks{status}` | 任务状态分布 |
| `itinerary_approvals{status}` | 审批状态分布 |
| `itinerary_badcases{status}` | badcase 状态分布 |
| `itinerary_task_completion_ratio` | COMPLETED / 全部任务 |
| `itinerary_badcase_rate_per_1000_tasks` | open badcase / 1000 任务 |
| `itinerary_approval_decision_seconds{decision}` | 审批创建到决定的等待时长 |
| `itinerary_approval_recovery_seconds{status}` | outbox 事件到任务恢复的时长 |
| `itinerary_outbox_backlog` | 待处理/处理中 outbox 数量 |

投影间隔：

```bash
BUSINESS_METRICS_ENABLED=true
BUSINESS_METRICS_INTERVAL_SECONDS=15
```

## 三块看板

| 看板 | UID | 内容 |
|---|---|---|
| Service Health | `itinerary-service-health` | 可用性、P95、5xx、限流、outbox、targets |
| Agent Quality | `itinerary-agent-quality` | fallback、熔断、工具错误、token、成本、工具延迟 |
| Business Funnel | `itinerary-business-funnel` | 任务/审批/badcase 分布、完成率、badcase 率、审批时延 |

看板文件：

```text
deploy/grafana/dashboards/
  itinerary-service-health.json
  itinerary-agent-quality.json
  itinerary-business-funnel.json
```

Grafana provisioning 每 30s 自动加载。

## 常用查询

```promql
max by (status) (itinerary_tasks)

max by (status) (itinerary_approvals)

max by (status) (itinerary_badcases)

max(itinerary_task_completion_ratio)

max(itinerary_badcase_rate_per_1000_tasks)

histogram_quantile(
  0.95,
  sum by (le, decision) (
    rate(itinerary_approval_decision_seconds_bucket[5m])
  )
)

sum by (status) (rate(itinerary_outbox_events_total[5m]))
```

## 排查

### 看板没有业务指标

1. worker 是否运行：

```bash
curl -s http://127.0.0.1:8001/readyz
```

应包含 `business_metrics: ok`。

2. worker metrics 是否有数据：

```bash
curl -s http://127.0.0.1:8001/metrics | grep itinerary_tasks
```

3. Prometheus 是否抓取 worker：

```bash
curl -s http://127.0.0.1:19090/api/v1/targets
```

`itinerary-worker` 必须是 `up`。

### 指标重复

业务 gauge 只在 worker 定义和导出；如果 API `/metrics` 也出现
`itinerary_task_completion_ratio`，说明旧镜像仍在运行，需要重建 API 镜像。

### 任务数增长很快

压测会创建大量任务；`itinerary_tasks{status="COMPLETED"}` 可能非常高。
这是数据库真实状态，不是指标错误。需要清理压测数据时，按 `session_id`
或 `task_id` 范围处理。

## 当前基线

2026-11-02 验证：

- worker `business_metrics: ok`
- Prometheus 能查到 `itinerary_tasks` / `itinerary_approvals` /
  `itinerary_badcases` / 完成率 / badcase 率
- 三块看板已 provision
