# Runbook: 模型网关

## 行为

```text
节点 → OpenAIChatGateway
  ├── 任务预算检查（token / cost）
  ├── LLM 缓存（classify/understand/summarize）
  ├── Redis 熔断 allow()
  ├── 主提供方
  │     ├── 成功 → success() → ledger/cache/metrics
  │     └── 失败 → failure() → 备用提供方
  └── 备用提供方
```

### 流式

- `respond` 节点使用 `gateway.stream()`，通过 LangGraph custom stream 转成 SSE
  `token` 事件。
- 首 token 之前失败才允许 fallback；首 token 之后失败直接结束，避免拼接两个
  模型的半截回答。
- 缓存命中时整段文本作为单个 token 返回。

### 熔断

状态：

```text
closed --失败达到阈值--> open --冷却--> half_open
half_open --成功--> closed
half_open --失败--> open
```

Redis key（`environment` 为 `local/test/...`）：

```text
<env>:circuit:<provider>:state        open | half_open
<env>:circuit:<provider>:failures
<env>:circuit:<provider>:opened_at
<env>:circuit:<provider>:trial        half_open 单试探锁
```

Redis 不可用时 `allow()` fail-open，业务继续调用模型。

配置：

```bash
CIRCUIT_BREAKER_ENABLED=true
CIRCUIT_FAILURE_THRESHOLD=5
CIRCUIT_COOLDOWN_SECONDS=30
CIRCUIT_TRIAL_SECONDS=5
```

### Prompt 版本

```bash
PROMPT_VERSION=v1
```

当前版本：

| purpose | 版本 |
|---|---|
| understand | v1、v2 |
| plan | v1 |
| summarize | v1 |

节点把实际版本写入 `CallContext.prompt_version`，最终落到 `llm_calls.prompt_version`。

### 任务预算

```bash
TASK_TOKEN_BUDGET=0          # 0 = 不限制
TASK_COST_BUDGET_USD=0       # 0 = 不限制
```

预算从 `llm_calls` 按 `task_id` 聚合；超限抛 `MODEL_BUDGET_EXCEEDED`，
节点按既有降级路径处理。

## 指标

| 指标 | 用途 |
|---|---|
| `itinerary_model_calls_total{provider,status,fallback}` | 调用量/状态/fallback |
| `itinerary_model_errors_total{provider,code}` | 错误分类 |
| `itinerary_model_tokens_total{provider,kind}` | token |
| `itinerary_model_cost_usd_total{provider}` | 成本 |
| `itinerary_model_circuit_open{provider}` | 熔断状态 |
| `itinerary_model_circuit_transitions_total{provider,to}` | 状态迁移 |
| `itinerary_model_circuit_rejected_total{provider}` | 熔断拒绝 |
| `itinerary_model_circuit_redis_errors_total` | 熔断 Redis 故障 |

## 排查

### 大量 fallback

```promql
sum by (provider, status) (rate(itinerary_model_calls_total[5m]))
sum(rate(itinerary_model_calls_total{fallback="True"}[5m]))
```

检查主模型 Key、网络、限流与 `MODEL_ERRORS` 的错误码。

### 熔断打开

```promql
itinerary_model_circuit_open == 1
```

- 冷却后会进入 half_open，只放一个试探；
- 试探成功自动 closed；
- 如果持续 open，检查主模型是否仍不可用；
- 需要人工重置时删除对应 Redis key：

```bash
redis-cli -p 56379 DEL local:circuit:deepseek:state \
  local:circuit:deepseek:failures \
  local:circuit:deepseek:opened_at \
  local:circuit:deepseek:trial
```

### 流式中断

- 首 token 前：会自动走备用；
- 首 token 后：不会 fallback，日志出现 `model stream failed`；
- 检查上游是否超时、代理是否缓冲；
- SSE 前端会保留已收到的部分文本。

### 预算超限

```bash
docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT task_id, SUM(prompt_tokens+completion_tokens) AS tokens, SUM(cost_usd) AS cost
   FROM llm_calls WHERE task_id='<task>' GROUP BY task_id;"
```

确认预算配置是否符合预期；`0` 表示关闭限制。

### Prompt 版本未生效

- 检查 `PROMPT_VERSION` 是否传入 API/worker；
- 查看 `llm_calls.prompt_version`；
- 某 purpose 没有该版本时会回退到默认版本，不会启动失败。
