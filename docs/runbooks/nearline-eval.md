# Runbook: 近线 / 在线质量评估

## 定位

当前实现是**近线评估**：

```text
worker 定时抽样最近任务
  → 读取 Checkpoint 状态
  → 确定性规则检查
  → 写 quality_findings
  → Prometheus 指标
```

不调用真实模型，不阻塞用户请求。

## 采样

```bash
QUALITY_EVAL_ENABLED=true
QUALITY_EVAL_INTERVAL_SECONDS=60
QUALITY_SAMPLE_RATE=0.05     # demo 5%，生产可从 1% 起步
QUALITY_LOOKBACK_MINUTES=60
QUALITY_MAX_TASKS=100
```

采样是确定性的：`sha256(task_id)` 映射到 [0,1)，小于采样率才评估；
同一任务不会因为随机数导致结果抖动。

## 检查项

| check | 含义 |
|---|---|
| `state_available` | Checkpoint 状态可读 |
| `slot_complete` | 目的地存在；或已向用户追问 |
| `policy_evaluated` | 有 `policy_result` |
| `options_available` | COMPLETED 任务有需要的候选方案 |
| `booking_consistent` | COMPLETED 任务有选择，且有差标通过/审批通过证明 |
| `no_error` | 状态不是 FAILED 且无 error |

失败 detail 只写原因，不写完整聊天内容。

## Findings

表：

```text
quality_findings
  finding_id / task_id / trace_id / tenant_id
  check_name / status / detail / created_at
```

唯一约束：

```text
(task_id, check_name)
```

同一任务同一检查重复采样时是 upsert，不是重复行。

API：

```bash
curl -s 'http://127.0.0.1:8081/quality/findings?limit=20' \
  -H 'X-Mock-User: u002'
```

需要 `badcase:manage` + 管理员。

## 指标

| 指标 | 用途 |
|---|---|
| `itinerary_quality_samples_total` | 已采样任务数 |
| `itinerary_quality_checks_total{check,status}` | 每项检查通过/失败 |
| `itinerary_quality_pass_ratio{check}` | 最近一批通过率 |

Grafana `Itinerary Agent Quality` 看板已加入：

- Near-line quality checks
- Quality pass ratio by check
- Quality samples / s

## 从 finding 到闭环

当前 findings 不自动创建 badcase，避免噪声任务刷爆工单。

推荐流程：

1. 在 `/quality/findings` 或 Grafana 发现持续失败；
2. 按 `task_id` / `trace_id` 找到 Checkpoint 和 Trace；
3. 人工确认是否真实缺陷；
4. 通过 `/feedback` 建 badcase；
5. 按 `badcase-loop.md` 写 regression case、导出、门禁、关闭。

后续可加：

- finding 聚合告警（连续 N 次失败）
- 一键从 finding 创建 badcase
- 在线采样 + LLM-as-judge

## 已验证

2026-11-02：

- worker `/readyz` 包含 `quality_eval: ok`
- 全量采样验证写入 findings 和 metrics
- 恢复 5% 采样后指标正常
- 空状态/缺失 options 的任务能被识别为 fail

## 边界

- 近线，不是实时拦截；
- 只做确定性检查，不做主观质量评分；
- 采样任务可能包含压测/空脚本对话，失败不代表线上缺陷；
- findings 需要人工 triage 后才进入 badcase。
