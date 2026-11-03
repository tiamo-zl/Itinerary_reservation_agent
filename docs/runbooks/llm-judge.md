# Runbook: 在线 LLM-as-judge

## 定位

对已完成任务做抽样主观质量评审：

```text
recent COMPLETED tasks
  → deterministic sample
  → compact structured payload
  → model_gateway（purpose=judge）
  → score 0-5 + pass/fail + reason
  → judge_results + Prometheus
```

它补充近线确定性检查，不替代离线金标集。

## 启用条件

只在 live 模型模式启用：

```bash
MODEL_MODE=live
JUDGE_ENABLED=true
JUDGE_INTERVAL_SECONDS=120
JUDGE_SAMPLE_RATE=0.01
JUDGE_LOOKBACK_MINUTES=120
JUDGE_MAX_TASKS=50
JUDGE_PROMPT_VERSION=v1
```

`MODEL_MODE=scripted` 时即使 `JUDGE_ENABLED=true` 也不会启动 judge worker；
worker `/readyz` 的 `judge` 会显示 `error`。

## 输入

只发送结构化摘要，不发送完整聊天：

- `request`：目的地、日期、预算、舱位、need_flight/hotel 等
- `options`：候选航班/酒店的少量字段
- `selected`
- `policy_result`：passed / requires_approval / violations
- `approval.status`
- `summary`

发送前统一做 PII 脱敏。不依赖 `CAPTURE_PROMPT`。

## 输出 schema

```json
{
  "score": 0,
  "verdict": "pass",
  "reason": "..."
}
```

- `score`：0–5 整数
- `verdict`：pass / fail
- `reason`：最多 500 字

模型网关负责结构化校验和一次修复；仍失败则本次跳过并记
`itinerary_judge_errors_total`。

## 存储

```text
judge_results
  task_id / prompt_version UNIQUE
  trace_id / tenant_id
  model / provider
  score / verdict / reason
```

同一任务同一 prompt 版本只评审一次，避免重复消耗模型成本。

API：

```bash
curl -s 'http://127.0.0.1:8081/quality/judgements?limit=20' \
  -H 'X-Mock-User: u002'
```

需要 `badcase:manage` + 管理员。

## 指标与看板

- `itinerary_judge_results_total{verdict}`
- `itinerary_judge_score`（0–5 直方图）
- `itinerary_judge_pass_ratio`
- `itinerary_judge_errors_total{code}`

Grafana `Itinerary Agent Quality` 已加入：

- LLM judge verdicts
- LLM judge pass ratio
- LLM judge average score

## 成本

- 采样 1% 起步
- 使用 STANDARD tier
- 所有调用写 `llm_calls`，包含 token、成本、provider、prompt_version
- 任务预算同样生效

## 校准

judge 是主观信号，必须用人工标签校准。当前提供 seeded 基线：

```bash
make judge-calibrate
```

- 数据集：`tests/eval/judge_calibration.jsonl`
- 24 条：12 pass / 12 fail
- 覆盖：槽位缺失、预算/差标矛盾、候选不一致、审批状态异常、
  摘要为空、状态不一致
- 标签来源：`seed`（确定性种子，后续替换为人工标注）
- 报告：`docs/status/judge-calibration.md`
- 需要 `MODEL_MODE=live` 和 DeepSeek Key

2026-11-02 seeded 基线（judge v1，DeepSeek）：

```text
verdict agreement = 0.875
score MAE         = 0.667
weighted kappa    = 0.758
fail recall       = 0.750
```

3 条 fail 漏判：`fail-missing-destination`、`fail-empty-summary`、
`fail-no-selection`。judge 倾向从 `options` 推断方案，忽略关键字段/
summary/selected 为空。建议出 judge v2 时明确这三条硬规则，再重新校准。

报告指标：

| 指标 | 含义 |
|---|---|
| verdict agreement | 人工/ judge 的 pass/fail 一致率 |
| score MAE | 0–5 分平均绝对误差 |
| quadratic weighted kappa | 分数一致性（考虑评分距离） |
| fail precision / recall / F1 | 把 fail 当正类 |
| confusion matrix | 人工 × judge |

可选门禁：

```bash
uv run python -m itinerary_agent.eval.judge_calibration \
  --fail-under-agreement 0.85 \
  --fail-under-kappa 0.6
```

更换 prompt 版本：

```bash
uv run python -m itinerary_agent.eval.judge_calibration \
  --prompt-version v2 --out docs/status/judge-calibration-v2.md
```

正式校准前：

1. 用真实任务和人工标注替换 seed 标签；
2. 至少覆盖不同 category / severity；
3. 达阈值后再把 judge 作为趋势信号，仍不作为 CI 硬门禁；
4. 每次修改 judge prompt 后重新校准。

## 问题处理

### judge pass ratio 下降

1. 看 `Itinerary Agent Quality` 的 verdict 趋势
2. 按 `task_id` 找到 Trace 和 Checkpoint
3. 查看 `judge_results.reason`
4. 人工确认后走 badcase 流程
5. 修复后重新录制 prompt/评测

### judge 调用全部失败

- 检查 `MODEL_MODE=live` 和模型 Key
- 检查 `itinerary_judge_errors_total{code}`
- 看 `llm_calls` 中 `purpose=judge` 的 status
- scripted 模式不会启动 judge

### 结果重复

`judge_results` 有 `(task_id, prompt_version)` 唯一约束；
worker 启动前会先查 `exists`。

## 边界

- LLM-as-judge 是主观信号，不直接作为 CI 硬门禁；
- 需要定期用人工标注校准；
- 当前只评 COMPLETED 任务；
- 不保存完整对话，只评结构化摘要。
