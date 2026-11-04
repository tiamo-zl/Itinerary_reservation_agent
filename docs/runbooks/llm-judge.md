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

## 一次性采样

常驻 worker 按 `JUDGE_SAMPLE_RATE` 低频抽样。人工校准前需要一批
确定的样本，可以用一次性命令，不启动 worker、不初始化 Milvus：

```bash
make judge-sample ARGS="--limit 50"
make judge-sample ARGS="--task-id <task_id> --task-id <task_id>"
make judge-sample ARGS="--limit 20 --dry-run"
```

它只读取最近 `COMPLETED` 任务的 Checkpoint，调用 live judge 并写入
`judge_results`；重复任务按 `(task_id, prompt_version)` 跳过。

如果本地库只有 load-test 任务（`request`、`selected`、`options` 为空），
judge 会把它们判为 fail，这类样本不适合做人工校准。此时改用下面的
离线 50 条校准集。

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

2026-11-03 seeded 基线（judge v1，DeepSeek）：

```text
verdict agreement = 0.875
score MAE         = 0.708
weighted kappa    = 0.753
fail recall       = 0.833
```

2 条 fail 漏判：`fail-missing-destination`、`fail-empty-summary`。
judge 倾向从 `options` 推断方案，忽略关键字段 / summary 为空。
建议出 judge v2 时明确硬规则，再重新校准。

同一天两次运行中，`pass-long-summary` 一次判 fail/3、一次判 pass/5。
即使 temperature=0，DeepSeek 仍可能给出不同结论；正式校准应固定
模型版本，并对关键样本做重复评审或多数投票。

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

## 离线 50 条人工校准

在线复核队列依赖真实任务；本地 demo 库可能只有 load-test 产生的
空任务，无法支撑 50 条校准。此时使用离线校准集：

```text
tests/eval/judge_calibration_50.jsonl   50 条，pass/fail 各 25
  → judge-label-prepare                对每条跑一次 judge
  → data/judge_labeling.jsonl          带上下文、不含 seed 标签
  → judge-label                        逐条人工标注
  → judge-label-finalize               生成 tests/eval/judge_calibration_human.jsonl
  → judge-calibrate-human              重跑 judge 并出校准报告
```

```bash
make judge-label-prepare   # 50 次 live judge 调用
make judge-label           # 交互式，p/f + 0-5 分 + 备注
make judge-label-finalize
make judge-calibrate-human
```

标注原则：

- `pass`：request/options/selected/policy/approval/summary 一致，
  满足日期、预算、区域、舱位和审批状态；
- `fail`：存在硬矛盾或关键遗漏，例如摘要声称已预订但 selected 为空、
  超预算却称通过、审批 rejected 却称已确认、目的地/舱位不一致；
- 分数 0-5：0-1 明显错误，2 关键遗漏，3 有瑕疵但可用，4 基本正确，
  5 完全正确且信息完整；
- 先独立判断，再看 judge reason；不要照抄 judge verdict，否则校准无意义。

`prepare` 不读取数据集里的 seed 标签，避免人工标注被预置答案影响。
至少需要 50 条且每类 ≥10 条，`judge-align` 才会给出 calibration gate。

### 自动 silver 标签（只用于冒烟）

没有人工标签时，可以用确定性规则生成 silver labels：

```bash
make judge-label-auto
make judge-calibrate-auto
```

- 输出：`tests/eval/judge_calibration_auto.jsonl`
- 报告：`docs/status/judge-calibration-auto.md` / `.json`
- 标签来源固定为 `auto-rule`，报告会明确标注“不能替代人工校准”

它用于验证“数据集 → judge → 指标 → 报告”链路，不用作发布门禁，
也不写入 `judge_calibration_human.jsonl`。

## 三类报告

| 报告 | 命令 | 输出 | 回答什么 |
|---|---|---|---|
| 工具报告 | `make judge-report` | `docs/status/judge-report.md` 第 1 节 | judge 是否启用、在线结果/复核队列、调用量/失败/token/成本/延迟 |
| 数据集报告 | `make judge-report` | 同上第 2 节 | 校准集规模、标签分布、来源、字段完整度、重复 ID、标签与 ID 前缀漂移 |
| 校准报告 | `make judge-calibrate-human` | `docs/status/judge-calibration-human.md` + `.json` | 人工 vs judge 的一致率、MAE、kappa、混淆矩阵、门禁 |

```bash
make judge-report            # 工具 + 数据集 + 已有校准 JSON 汇总
make judge-calibrate-human   # 重新调用 judge 并生成人工校准 md/json
make judge-report            # 校准 JSON 生成后再汇总一次
```

`judge-report` 是只读聚合，不会调用模型；`judge-calibrate-human`
会重新跑 judge，因此需要 live key。seeded 基线用 `make judge-calibrate`，
输出 `docs/status/judge-calibration.md` 和 `.json`。

报告里固定记录：

- 数据集路径与 SHA-256 前缀；
- prompt 版本、模型、标签来源；
- 门禁参考值：`agreement ≥ 0.85`、`kappa ≥ 0.6`（不是 CI 硬门禁）。

## 在线人工复核与 OpenJudge 校准

judge 结果默认进入人工复核队列（`review_status=pending`）。

### 1. 导出待复核

```bash
make judge-review-export
```

生成 `data/judge_review.jsonl`，每人一行：

```json
{
  "judge_id": "...",
  "task_id": "...",
  "trace_id": "...",
  "judge_score": 2,
  "judge_verdict": "fail",
  "judge_reason": "...",
  "human_score": null,
  "human_verdict": null,
  "comment": ""
}
```

人工填写 `human_score`（0–5）、`human_verdict`（pass/fail）和 `comment`。

### 2. 导入人工标签

```bash
make judge-review-import
```

也可以走 API：

```bash
curl -X PATCH http://127.0.0.1:8081/quality/judgements/<judge_id> \
  -H 'Content-Type: application/json' \
  -H 'X-Mock-User: u002' \
  -d '{"human_score":5,"human_verdict":"pass","comment":"审核通过"}'
```

### 3. 生成配对文件并校准

```bash
make judge-review-pairs
make judge-align
```

`judge-align` 使用 **OpenJudge align-human**（Apache-2.0）的独立脚本
`scripts/openjudge_align_human.py`，只需要标准库：

- TPR / TNR / F1，带 bootstrap 95% CI
- Cohen's kappa
- Gwet's AC1（处理类别不平衡）
- directional bias
- calibration gate

门槛：

```text
>= 50 human labels
>= 10 per class
TPR >= 0.8
TNR >= 0.8
```

样本不足时会返回 `insufficient_evidence`，不会假装已校准。

### 与 OpenJudge 的关系

- **可以直接接入**的是 `align-human` 校准脚本；它不依赖 OpenJudge 包。
- OpenJudge 的完整 graders/GradingRunner 可以替换 judge 实现，但会引入额外框架；
  当前项目继续使用自己的 `model_gateway` + judge prompt。
- 人工标注 UI 仍由本项目提供（当前是 CLI/API，后续可接产品后台）。

脚本来源：

```text
https://github.com/agentscope-ai/OpenJudge
skills/eval_pipeline/03-align-human/scripts/calibration.py
```

License 文本见 `docs/third-party/OpenJudge-APACHE-2.0.txt`。

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
