# LLM-as-judge 质量报告

- 生成时间：2026-11-04T00:53:27+00:00
- 数据集：`tests/eval/judge_calibration_50.jsonl`

## 1. 工具报告

### 配置

| 项 | 值 |
|---|---|
| MODEL_MODE | live |
| JUDGE_ENABLED | False |
| judge prompt | v1 |
| sample rate | 0.01 |
| interval (s) | 120 |
| lookback (min) | 120 |
| max tasks | 50 |
| primary provider | deepseek |
| standard model | deepseek-flash |

### 在线结果与复核队列

| 指标 | 值 |
|---|---|
| judge_results 总数 | 2 |
| pass | 0 |
| fail | 2 |
| pending 复核 | 2 |
| reviewed | 0 |
| 平均分 | 0.5000 |
| 最近一次 | 2026-11-03 15:14:54.493270+00:00 |

### judge 模型调用

| 指标 | 值 |
|---|---|
| 调用数 | 26 |
| 成功 | 26 |
| 失败 | 0 |
| cache hits | 0 |
| tokens | 20514 |
| cost (USD) | 0.0000 |
| 平均延迟 (ms) | 3041.0 |

> cost=0 但 tokens>0：检查 `config/pricing.yaml` 是否覆盖当前模型。

## 2. 数据集报告

### 校准集

| 指标 | 值 |
|---|---|
| 路径 | `tests/eval/judge_calibration_50.jsonl` |
| SHA-256 前缀 | `61b9475234412528` |
| 用例数 | 50 |
| 标签分布 | fail=25, pass=25 |
| 标签来源 | seed=50 |
| 重复 ID | 无 |
| ID 前缀与标签不一致 | 无 |
| request 空字段 | destination_city=1, start_date=1, end_date=1, budget_limit=1 |
| options 全空 | 1 |
| selected 为空 | 2 |
| summary 为空 | 1 |
| 缺 policy_result | 0 |
| 缺 approval | 0 |

### 人工标签集

数据集不存在。

## 3. 校准报告

未找到 `docs/status/judge-calibration-human.json`。先运行：

```bash
make judge-calibrate-human
```
