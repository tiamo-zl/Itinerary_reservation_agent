# 质量闭环手册：观测、评测集与 Badcase 回流

本手册说明如何在本地 mock 形态下完成一条完整的质量闭环：

```text
在线运行 → 发现问题 → 定位归因 → 固化为回归用例 → 门禁拦截 → 关闭
```

三份文档的分工：

| 文档 | 负责 |
|---|---|
| `docs/runbooks/observability.md` | 观测栈如何启动、外部栈故障排查 |
| `docs/runbooks/p0-acceptance.md` | P0 功能/降级/安全的人工验收步骤 |
| `docs/adr/0006-quality-operations-and-console-retirement.md` | 为什么拆分三类职责、控制台退役的决策与退出条件 |
| **本文** | 日常如何观测、如何扩充评测集、如何把 badcase 写成回归用例 |

> 本文第 1–4 节描述**当前形态**（自建控制台仍在）的操作方法；第 5 节描述
> **目标形态**（控制台退场、五件套为观测主干）的操作方法。迁移完成前两套并存，
> 以第 5 节的退出条件作为切换依据。
>
> 控制台状态（2026-11-02）：已冻结为 demo，正式退役暂缓；
> 不作为观测/业务/质量的事实源。见 ADR 0006。

所有命令默认在仓库根目录执行。

---

## 0. 闭环总览

```text
① 在线运行              ② 发现问题                ③ 定位与归因            ④ 固化为回归
/chat、/resume    →   /traces/overview        →   trace 调用树 + 流转图  →   反馈成 badcase
审批/worker/outbox     Grafana / Prometheus        Checkpoint 历史          →   写成 eval 用例
                       Kibana / Langfuse           llm_calls / 审计表       →   门禁变绿
                                                                              → 状态 fixed
```

三个必须先理解的设计事实：

1. **一次用户请求 = 一个 trace**；每个节点或层操作 = 一个 span。`resume` 复用任务首次请求的 `trace_id`，所以「聊天 → 审批 → 恢复 → 下单」是同一条链。
2. span **无论 OTel 是否开启都会写入 PostgreSQL 的 `spans` 投影表**；写失败只记日志，不影响业务。控制台看到的是全量数据，不是采样数据。
3. 评测集是**离线、确定性、不调用真实模型**的；badcase 回放并入同一个 runner 和同一套阈值，所以坏用例会让 CI 变红。

---

## 1. 如何观测

观测分四个平面。排查顺序建议：

```text
概览 → 指标 → 单条 trace → 日志 / 分布式追踪
```

### 1.1 请求级：控制台与 trace 接口（最常用）

统一入口为 Higress `http://127.0.0.1:8081`。

| 页面 | 路径 | 看什么 |
|---|---|---|
| 线上概览 | `/overview` | trace/span 总数、错误率、P95、分层延迟、LLM 调用与成本、审批/任务/badcase 分布、最近 trace |
| Trace 回放 | `/trace/{trace_id}` | 调用树、Checkpoint 状态历史、聊天记录、审批信息、反馈表单 |
| 流转图 | `/flow/{trace_id}` | 本次实际走过的节点/边，边上有 label 与条件 |
| 对话记录 | `/conversations` | 会话列表与消息 |
| 审批工作台 | `/approvals` | pending 与已处理审批 |

对应 API（便于脚本化）：

```bash
curl -s http://127.0.0.1:8081/traces/overview -H 'X-Mock-User: u002'
curl -s 'http://127.0.0.1:8081/traces?limit=20' -H 'X-Mock-User: u002'
curl -s http://127.0.0.1:8081/traces/$TRACE_ID -H 'X-Mock-User: u001'       # 调用树
curl -s http://127.0.0.1:8081/traces/$TRACE_ID/flow -H 'X-Mock-User: u001'  # 流转图
curl -s 'http://127.0.0.1:8081/tasks/$TASK_ID/history?limit=10' -H 'X-Mock-User: u001'
curl -s http://127.0.0.1:8081/tasks/summary -H 'X-Mock-User: u002'
curl -s http://127.0.0.1:8081/tasks/$TASK_ID/traces -H 'X-Mock-User: u001'
```

#### span 命名约定

调用树按 `parent_span_id` 还原；span 名与 layer 是固定约定：

| span 名 | layer | 含义 | 关键 attributes |
|---|---|---|---|
| `orchestration.node.understand` / `.plan` / `.search` / `.policy` / `.approval` / `.confirm` / `.book` / `.respond` | `orchestration` | LangGraph 节点 | `trace_id`、`task_id` |
| `knowledge.search_policy` | `knowledge` | 制度检索（混合召回 + 图扩展） | `tenant_id` |
| `control.check_policy` | `control` | 确定性差标判定 | `tenant_id` |
| `model.<purpose>` / `model.<purpose>.stream` | `model` | 每次模型调用（含流式） | `provider`、`model`、`prompt_version`、`fallback_from` |
| `tool.<tool_name>` | `tools` | 每次工具调用 | `tool_name`、`side_effect`、`risk` |

#### 调用树的读法

按以下顺序定位：

1. **差在哪个节点**：找 `status=error` 的 `orchestration.node.*`，或缺失的节点。
2. **是模型还是工具**：展开子 span。`model.*` 看 provider/fallback，`tool.*` 看 risk/side_effect。
3. **差标是否判错**：看 `orchestration.node.policy` 之后是否按 `requires_approval` 进入 approval。
4. **状态级回放**：配合 `/tasks/{id}/history` 对照 Checkpoint 每一步的状态与 `revision`。

#### 流转图的两个已知行为

- 只取 `orchestration.node.*` span；
- interrupt 恢复会重跑当前节点，已自动去重，不会产生自环。

边上的 label/条件来自静态图，可用于验证分支是否符合预期，例如只有 `requires_approval=true` 才应出现 `policy → approval`。

### 1.2 指标级：Prometheus 与 Grafana

- 抓取：API `:8000/metrics`、Worker `:8001/metrics`
- Grafana：`http://127.0.0.1:13000`，看板 UID `itinerary-agent`
- Prometheus Targets：`http://127.0.0.1:19090/targets`（`itinerary-api`、`itinerary-worker`、`otel-collector` 必须 `up`）

指标按问题域分组：

| 问题域 | 指标 | 用法 |
|---|---|---|
| 流量/延迟 | `itinerary_http_requests_total{method,path,status}`、`itinerary_http_request_duration_seconds_bucket` | 路径已模板化（`/tasks/{id}`），可按 path 聚合 |
| 模型 | `itinerary_model_calls_total{provider,status,fallback}`、`itinerary_model_errors_total`、`itinerary_model_tokens_total`、`itinerary_model_cost_usd_total` | `status` 含 `short_circuited`；`fallback="True"` 表示主备切换 |
| 熔断 | `itinerary_model_circuit_open{provider}`、`itinerary_model_circuit_transitions_total`、`itinerary_model_circuit_rejected_total` | 主模型故障时先看这里 |
| 工具 | `itinerary_tool_calls_total{tool,status,code}`、`itinerary_tool_duration_seconds` | 定位哪个外部系统慢或失败 |
| 异步 | `itinerary_outbox_events_total{status}`、`itinerary_outbox_backlog` | 审批恢复卡住时 backlog 上涨 |
| 网关 | `itinerary_rate_limited_total{scope}`、`itinerary_sse_connections` | 限流触发、在线会话数 |
| 清理 | `itinerary_retention_deleted_rows_total{table}` | 保留策略是否在运行 |

常用 PromQL：

```promql
sum by (status) (rate(itinerary_http_requests_total[5m]))

histogram_quantile(
  0.95,
  sum by (le) (rate(itinerary_http_request_duration_seconds_bucket[5m]))
)

sum by (provider, status) (rate(itinerary_model_calls_total[5m]))
sum(rate(itinerary_model_calls_total{fallback="True"}[5m]))

itinerary_outbox_backlog

sum by (tool, status, code) (rate(itinerary_tool_calls_total[5m]))

itinerary_retention_deleted_rows_total
```

告警规则见 `deploy/prometheus/alerts.yml`，排查方式见 `docs/runbooks/observability.md`。

### 1.3 日志级：Kibana

链路：

```text
应用 JSON stdout → Docker json-file → Collector filelog → Elasticsearch → Kibana
```

- Kibana：`http://127.0.0.1:5601`
- data stream：`logs-itinerary`

**当前限制**：应用 JSON 的字段没有提升为结构化字段，`trace_id`、`span_id`、`task_id`、`request_id`、`tenant_id`、`user_id` 都在 `body.text` 内，只能全文检索：

```text
body.text : "p0-manual-trace"
body.text : "ERROR"
body.text : "<request_id>"
```

核对日志是否进入 ES：

```bash
curl -s 'http://127.0.0.1:9200/_data_stream/logs-itinerary?pretty'
curl -s 'http://127.0.0.1:9200/logs-itinerary/_count?pretty'
```

### 1.4 分布式追踪：OTel → Collector → SkyWalking / Langfuse

- Collector：`4317`（gRPC）、`4318`（HTTP）、`8889`（自身指标）
- **Langfuse**（`http://127.0.0.1:13002`）：只接收带 `task_id` 的 span，是业务链路的 LLM 视图；按 `task_id` 搜索 trace，查看 span 时间、token、成本、model/provider/fallback。
- 默认 `CAPTURE_PROMPT=false`，不保存完整 prompt/completion；需要看内容时显式开启。
- **SkyWalking**（`http://127.0.0.1:18080`）：已知外部栈限制——原始 span 会写入 `sw_zipkin_span-*`，但未生成 `sw_segment`，服务目录为空。它只用于确认「原始 span 是否到达」，业务排查以自建控制台和 Langfuse 为准。

确认数据流：

```promql
sum(rate(otelcol_receiver_accepted_spans[5m]))
sum(rate(otelcol_exporter_sent_spans[5m]))
sum(rate(otelcol_exporter_send_failed_spans[5m]))
```

```bash
curl -s 'http://127.0.0.1:9200/_cat/indices/sw_zipkin_span-*?h=index,docs.count'
docker logs --tail 100 itinerary-reservation-agent-otel-collector-1
```

### 1.5 直接查库（最确定）

控制台是投影，数据库才是事实源：

```bash
docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT name, layer, status, duration_ms, start_time
     FROM spans WHERE trace_id='$TRACE_ID' ORDER BY start_time;"

# 模型调用明细：token、成本、fallback
docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT purpose, provider, model, status, fallback, prompt_tokens,
          completion_tokens, cost_usd, created_at
     FROM llm_calls WHERE trace_id='$TRACE_ID';"
```

排查顺序总结：

```text
/traces/overview 看趋势
  → Grafana 确认问题类别
    → /trace/{id} 看调用树和 Checkpoint
      → spans / llm_calls 精确核实
        → Kibana 按 trace_id 查日志
```

---

## 2. 如何做评测集

### 2.1 结构

```text
tests/eval/
  cases/
    slot_cases.jsonl        需求理解：别名、相对日期、默认槽位
    policy_cases.jsonl      差标：职级/城市/生效日期/默认回退/审批
    retrieval_cases.jsonl   RAG：关键词、语义、引用、例外、父子、表格、不足
    retrieval_kb.json       检索评测共享条款树/边/表格
    approval_cases.jsonl    guard 准入与 revision 修改
    prompt_cases.jsonl      按 prompt_version 分组的录制输出 A/B
    badcase_cases.jsonl     badcase 回放（内嵌 case）
    scenario_cases.jsonl    12 个端到端场景清单
  thresholds.json           CI 阈值
```

当前规模：slot 16、policy 16、retrieval 10、approval 14、prompt 6、badcase 4、scenario 12。

### 2.2 运行与判定

```bash
make eval                                                            # 全部 suite + 阈值
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --suite retrieval
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --json      # CI 归档
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --no-enforce # 只报告不失败
```

注意：`make eval` 不转发额外参数，只跑指定 suite 时请直接用上面的 `python -m ...` 形式。

输出是 `suite / cases / passed / metrics` 表；阈值不达标时进程返回 1，并列出 `suite.metric: actual < required`。`--json` 还包含每个 suite 的 `failures`（带 `expected` / `actual`），是 triage 和写新用例的主要素材。

### 2.3 每个 suite 测什么

| suite | 指标 | 实际执行 | 当前阈值 |
|---|---|---|---|
| `slot` | `exact_match_rate`、`field_accuracy` | 规则归一化 `normalize_payload`（不是模型） | 0.85 / 0.95 |
| `policy` | `decision_accuracy` | `control.check_policy` 确定性判定 | 0.95 |
| `retrieval` | `recall_at_5`、`mrr`、`citation_precision`、`insufficient_accuracy` | `KnowledgeService` + `MemoryPolicyStore` + `StaticEmbedder` + `StaticDenseStore` | 0.95 / 0.85 / 0.7 / 0.95 |
| `approval` | `scenario_pass_rate` | `guard_action`、`apply_amendment` | 1.0 |
| `prompt` | `<version>_exact_match_rate`、`overall_exact_match_rate` | 重放录制的 `raw_output`，按 `prompt_version` 分组 | 0.8 |
| `badcase` | `replay_pass_rate` | 按 wrapper 的 `suite` 分派到上面五个 | 1.0 |

两个关键理解：

1. **retrieval 的语义召回被模拟**：`dense_ids` 固定，`StaticDenseStore` 直接返回预设结果；关键字召回由 `MemoryPolicyStore` 对 `retrieval_kb.json` 做子串匹配。所以它测的是**检索编排、图扩展、引用和不足判定**，不是真实向量质量。
2. **prompt suite 是唯一贴近模型输出的**：把某次录制/真实的模型原始输出贴成 `raw_output`，重放后断言归一化槽位。做 prompt A/B 就是同一批 case 分别录制 v1、v2 输出，比较各自的 `*_exact_match_rate`。

### 2.4 用例格式

```jsonl
// slot：start_weekday（0=周一）、duration_days 为派生断言
{"id":"slot-1","today":"2026-10-21","raw":{"destination":"北京","departure_date":"下周二"},"expected":{"destination_city":"北京","start_weekday":1}}

// policy：断言「是否通过 + 是否需要审批」
{"id":"policy-1","level":"L2","destination_city":"北京","hotels":[{"price":800}],"rules":[{"id":"h-l2","match":{"employee_level":["L2"]},"category":"hotel","limit":500,"severity":"block","allow_approval":true}],"expected_passed":false,"expected_requires_approval":true}

// retrieval：expected 为必须命中的 clause_id；可选 expected_table_rows
{"id":"ret-1","query":"住宿标准","dense_ids":["c1"],"filters":{"employee_level":"L2","city_tier":1},"expected":["c1","c2"],"expected_insufficient":false}

// approval：guard 或 amendment 两类
{"id":"appr-1","action":"book_hotel","status":"EXECUTING","policy_passed":false,"requires_approval":true,"approval_status":"pending","confirmed":true,"expected_code":"APPROVAL_REQUIRED"}

// prompt：必须带 prompt_version 和录制的 raw_output
{"id":"prompt-1","prompt_version":"v2","today":"2026-10-21","raw_output":"{\"destination\":\"上海\"}","expected":{"destination_city":"上海"}}
```

JSONL 加载会跳过空行和以 `#` 开头的注释行。新增 retrieval 用例涉及的条款时，同步更新 `retrieval_kb.json` 的 `clauses` / `edges` / `tables`，否则关键字召回和图扩展找不到目标。

### 2.5 新增一条用例的流程

1. **选 suite**：问题出在确定性规则 → `policy`；需求解析 → `slot`；检索/引用 → `retrieval`；准入/改单 → `approval`；模型输出 → `prompt`；只有端到端才能复现 → 先补 `scenario_cases.jsonl` 指向的 e2e 测试。
2. **追加一行 JSONL** 到对应 `.jsonl`。
3. **先单独验证**用 `--suite <name> --no-enforce`，确认失败是「用例复现了问题」而不是格式错误。
4. **修复后确认变绿**，再跑全量 `make eval`。
5. **需要时调整阈值**（见 2.6）。

### 2.6 阈值策略

`thresholds.json` 的键是 suite 名，值是 `{metric: minimum}`：

- 指标缺失也算失败（`metric missing`）；
- 惯例是**略低于当前基线，只升不降**；
- `approval` 和 `badcase` 是 1.0，属于硬门禁；
- `--suite` 会同时过滤结果和阈值，单跑一个 suite 时其余 suite 不参与判定。

### 2.7 场景清单与 CI

- `scenario_cases.jsonl` 不是执行测试，而是**清单校验**：`test_scenario_manifest` 断言 `tests/test_scenarios.py` 中存在同名测试函数，防止评测集与 e2e 测试脱节。
- CI（`.github/workflows/ci.yml`）在 `pytest`（覆盖率门槛 70%）之后执行 `python -m itinerary_agent.eval.cli`，与本地 `make eval` 使用同一套 runner 和阈值。

### 2.8 已知边界

- 全离线：不调用真实模型、不连 Milvus，适合 CI 稳定运行；**live 质量必须靠 `prompt` suite 录制真实输出来覆盖**。
- slot/policy 测的是规则与确定性控制，不覆盖模型理解错误；这类问题应先归类到 `prompt` 或端到端场景。
- retrieval 的 `recall_at_5` 基于图扩展后的 `citations`，`mrr` 基于 `trace.seed_ids`；两者不一致时先看种子排序再看扩展结果。

---

## 3. 如何做 Badcase

### 3.1 记录：两个入口

**入口 A：控制台**。`/trace/{trace_id}` 页面底部有「反馈 / Badcase 回流」表单，填写类别、严重度、用户输入、期望、实际、备注，提交即生成 badcase。

**入口 B：API**：

```bash
curl -s -X POST http://127.0.0.1:8081/feedback \
  -H 'X-Mock-User: u001' \
  -H 'Content-Type: application/json' \
  -d '{
    "trace_id":"'$TRACE_ID'",
    "task_id":"'$TASK_ID'",
    "category":"policy",
    "severity":"high",
    "user_input":"去北京，住800的酒店，我是L2",
    "expected":"应要求审批",
    "actual":"直接通过",
    "comment":"差标未拦截"
  }'
```

实现要点：

- 路由先做 `scrub()` 脱敏，再交给 `FeedbackService`；服务只补 `tenant_id` 和时间，状态固定 `open`。
- 提交需要 `feedback:write` scope（mock 模式下员工具备）。
- **列表和推进状态需要 `badcase:manage` + 管理员**（mock 模式用 `u002`）。
- 反馈只记录问题，**不改变任务状态**。

### 3.2 存储与状态

表 `badcases` 字段：

```text
badcase_id / trace_id / task_id / tenant_id / category / severity
user_input / expected / actual / comment / root_cause
status / created_at / updated_at
```

`PATCH /badcases/{badcase_id}` 只接受三类字段：

- `status`：`open` / `reproduced` / `fixed` / `closed`
- `root_cause`
- `comment`

建议的运营语义（代码不强制，靠团队约定）：

```text
open ──复现成功──▶ reproduced ──修复并加回归用例──▶ fixed ──观察一周无复发──▶ closed
```

概览页 `/overview` 会按状态展示 badcase 数量，管理员可在页面上直接推进状态。

### 3.3 category 与 suite 的对应

`category` 是枚举，正好对应分层，是归因的第一把钥匙：

| category | 通常对应的层 | 建议落到哪个 suite |
|---|---|---|
| `understand` | `orchestration.node.understand` + `model.*` | `slot` 或 `prompt` |
| `plan` | `orchestration.node.plan` + `knowledge.*` + `model.*` | `prompt` / `retrieval` |
| `tool` | `tool.*` | 端到端场景（补 `scenario`） |
| `policy` | `control.check_policy` | `policy` |
| `rag` | `knowledge.search_policy` | `retrieval` |
| `approval` | `orchestration.node.approval` + `guard_action` | `approval` |
| `booking` | `orchestration.node.book` + `tool.*` | 端到端场景 |
| `other` | — | 先定性 |

### 3.4 从 badcase 到回归用例

目前**没有自动导出脚本**：需要从 `badcases` 表导出后，按 suite 手工组装成 `badcase_cases.jsonl` 的 wrapper 格式。

1. 导出 open 的 badcase：

```bash
docker exec itinerary-reservation-agent-postgres-1 psql -U itinerary -d itinerary -c \
  "SELECT badcase_id, trace_id, task_id, category, severity,
          user_input, expected, actual
     FROM badcases WHERE status='open' ORDER BY created_at;"
```

2. 用 trace 回放和 Checkpoint 历史确认**最小复现输入**；`user_input` 通常还不是可直接断言的结构化输入，需要还原成对应 suite 的 case 形态。
3. 追加到 `tests/eval/cases/badcase_cases.jsonl`：

```jsonl
{"id":"badcase-policy-l2-hotel-800","suite":"policy","case":{
  "id":"replay-policy-l2-hotel-800",
  "level":"L2","destination_city":"北京",
  "hotels":[{"price":800}],
  "rules":[{"id":"h-l2","match":{"employee_level":["L2"]},"category":"hotel","limit":500,"severity":"block","allow_approval":true}],
  "expected_passed":false,"expected_requires_approval":true}}
```

wrapper 的 `suite` 只支持 `slot` / `policy` / `retrieval` / `approval` / `prompt`；其它值会被判为 unknown suite 并失败。

4. 运行：

```bash
PYTHONPATH=src uv run python -m itinerary_agent.eval.cli --suite badcase
# 或全量
make eval
```

因为 `replay_pass_rate` 阈值是 **1.0**，问题没修好之前 CI 一定是红的——这就是把线上问题转成发布门禁的机制。

5. 修复后把 badcase 状态推进到 `fixed`，并填写 `root_cause`（例如「policy 规则 match 缺少 city_tier 维度」），便于后续检索同类问题。

### 3.5 一个完整例子

```text
现象：用户说「L2 住 800 的酒店」，Agent 直接通过未要求审批
  ↓ 概览页发现 open badcase +1，category=policy
  ↓ /trace/{id}：control.check_policy 返回 passed=true（不是模型问题）
  ↓ 定位：policy 规则中 h-l2 的 limit 配成了 900
  ↓ 反馈已记录期望/实际
  ↓ 从 user_input 还原成 policy case，追加到 badcase_cases.jsonl
  ↓ make eval → badcase 失败（红）
  ↓ 修正规则/判定逻辑
  ↓ make eval 全绿
  ↓ badcase 状态 fixed，root_cause 写明
```

---

## 4. 日常节奏

| 频率 | 动作 | 看哪里 |
|---|---|---|
| 每次改动 / 提 PR | `make lint && make typecheck && make test && make eval` | 本地输出 |
| 每次发版前 | Prometheus targets 全 up、Grafana 无异常、`make eval` 全绿 | Grafana / CI |
| 每天 | `/traces/overview` 错误率、P95、outbox backlog、open badcase 数 | 控制台 / Grafana |
| 每周 | 清 `open` badcase：复现 → 归档 suite → 加回归用例 → 推进状态 | `/overview` + `badcases` 表 |
| 每月 | 根据新基线抬 `thresholds.json`；清理长期 `closed` badcase | 仓库 |

### 闭环是否真的通了：最小验收

1. 一次 `/chat` 能在 `/traces` 按 trace 找到，调用树节点与层级正确；
2. 在 `/trace/{id}` 提交反馈后，`/badcases?status=open` 能看到，且状态可推进；
3. 把该问题写成 `badcase_cases.jsonl` 后，故意让它失败时 `make eval` 返回 1；
4. 修好后全绿，CI 同步变绿；
5. Grafana 能看到对应请求的 HTTP/模型/outbox 指标，Kibana 能按 `trace_id` 全文搜到日志。

---

## 5. 工业级演进：控制台退场后的四件事

`/flow`、`/trace`、`/overview` 是把**平台观测、业务状态、质量运营**揉在一起的自建视图。
工业级改造不是简单弃页面，而是把三类职责分别交给成熟系统。决策与备选方案见
`docs/adr/0006-quality-operations-and-console-retirement.md`，本章是可执行的落地方法。

**页面是视图，数据是资产**：`spans` 投影、`badcases` 表和相关 API 继续保留，
只有观测视图退役。

### 5.1 职责归位

| 职责 | 系统 of record | 操作接口 |
|---|---|---|
| 平台观测 | Prometheus/Grafana、ELK、Trace 后端 | 看板、查询、告警 |
| 业务状态 | PostgreSQL + 产品后台 | 带 RBAC 的管理 API |
| 质量运营 | 评测数据集 + 工单系统 | CI 门禁、工单流程 |

现有能力的目标载体：

| 现有能力 | 目标载体 | 前置条件 |
|---|---|---|
| `/overview` 聚合 | Grafana 三块看板 | 业务 KPI 导出为指标或只读 SQL 数据源 |
| `/trace/{id}` 调用树 | Trace 后端 UI（SkyWalking 或 Tempo/Jaeger） | 修好 SkyWalking 或替换后端 |
| Checkpoint/聊天/审批回放 | 产品后台 | 管理页面 + RBAC，复用现有 API |
| `/flow/{id}` 流转图 | Trace 时序或产品事件表 | 决定它是产品解释性还是观测能力 |
| `feedback` 表单 | 工单系统 + 数据集仓库 | 工单联动、`trace_id` 深链 |
| `badcases` 列表/状态 | 工单系统（PG 表做副本） | 状态机与 SLA 约定 |

> Langfuse 不是通用 Trace 后端：它只接收带 `task_id` 的 span。弃掉自建 trace 视图前，
> 必须有一个能展示完整调用树的后端。

### 5.2 如何观测

#### 先定义 SLO

| 类别 | SLI | 目标示例 |
|---|---|---|
| 可用性 | `/chat`、`/resume` 的 5xx 比例 | 99.5% / 28 天 |
| 延迟 | `/chat` 首包、`/resume` 端到端 P95 | P95 < 2s（首包） |
| 业务质量 | 任务完成率、审批恢复时延、下单成功率 | 完成率 ≥ 95%，恢复 P95 < 10s |

SLI 采用率与燃烧率（以 99.5% 为例）：

```promql
# 可用性 SLI
sum(rate(itinerary_http_requests_total{status!~"5.."}[5m]))
/
clamp_min(sum(rate(itinerary_http_requests_total[5m])), 0.001)

# 1h 燃烧率；>1 表示错误预算消耗快于预算
(1 - (
  sum(rate(itinerary_http_requests_total{status!~"5.."}[5m]))
  / clamp_min(sum(rate(itinerary_http_requests_total[5m])), 0.001)
)) / (1 - 0.995)
```

告警采用多窗口燃烧率（如 1h 14.4x + 6h 6x）作为主告警；
`deploy/prometheus/alerts.yml` 中现有的 8 条阈值规则保留为补充。

#### 指标分三层，不混在一个面板

| 层 | 指标 | 受众 |
|---|---|---|
| 平台层 | HTTP RED、连接池、Redis、PG、outbox backlog | SRE |
| AI 层 | 模型调用/失败/fallback/熔断、token、成本、缓存、工具错误分类 | 平台 + 算法 |
| 业务层 | 任务状态分布、审批等待时长、恢复成功率、下单成功率、open badcase 数 | 产品 + 运营 |

业务层指标当前只存在于 PG，是控制台退场后最容易丢失的一块；必须导出为指标，
或通过 Grafana 的只读 PostgreSQL 数据源查询。

#### 三块看板覆盖原 overview

1. **Service Health**：RED、SLO 燃烧率、依赖健康、outbox 积压。
2. **Agent Quality**：模型 fallback/熔断、工具错误、检索耗时、按 `prompt_version` 的调用量。
3. **Business Funnel**：任务状态流转、审批时延、完成率、成本/任务、badcase 趋势。

看板通过 Grafana provisioning 随代码走，和现有 `Itinerary Agent` 看板同一机制。

#### Trace 后端与连接键

- 修好 SkyWalking（让 OTLP/Zipkin 生成 `sw_segment`），或替换为 Tempo/Jaeger；
- API 响应头增加 `X-Trace-Id`（目前只有 `X-Request-ID`），让用户和客服能直接提供 trace；
- `trace_id` 作为跨系统连接键：日志、指标 exemplar、工单、评测用例、告警都用它；
- 观测完备性验收：每次 `/chat` 必须包含 `orchestration.node.*`，并有至少一个
  `model.*` 或 `knowledge.*` span。

#### 日志结构化

在 Collector 的 filelog 管道增加 `json_parser`，把 `trace_id`、`span_id`、`task_id`、
`request_id`、`tenant_id`、`user_id` 提升为 ES 字段。否则页面退役后，Kibana 的排障
能力还不如当前控制台。

### 5.3 如何做评测集

在现有离线金标集之上补成三层：

| 层 | 数据来源 | 频率 | 用途 |
|---|---|---|---|
| 离线金标 | 人工设计 + badcase 回归 | 每个 PR / CI | 硬门禁，快、稳定、可解释 |
| 近线回放 | 生产采样 trace 的输入重放 | 每日 / 发版前 | 覆盖真实分布与长尾 |
| 在线评估 | 采样流量 + 规则检查 + LLM-as-judge | 持续 | 发现金标集外的漂移 |

必须补齐的四件事：

1. **版本化**：每条结果记录 `dataset_version`、`prompt_version`、`model`、`rules_version`；
   否则不同批次指标不可比，A/B 没有意义。
2. **数据集拆分**：`golden`、`regression`、`holdout` 三类；badcase 进入 `regression`，
   `holdout` 不参与调参。
3. **统计严谨**：门禁看置信区间或配对比较，不因单条用例波动调阈值；调阈值必须附基线报告。
4. **失败可追**：用例带 `source_trace_id`，失败时能直接跳到 Trace 后端。

在线评估的最小形态：

- 采样 1%–5% 的 `/chat`，异步执行规则检查（槽位完整、政策判定、引用存在、工具成功）；
- LLM-as-judge 只用于主观项，并定期与人工标注做一致性校准；
- 结果写成指标（如 `eval_online_pass_rate{check=...}`），进 Grafana，与发版时间对齐观察。

门禁节奏建议：

```text
每个 PR     → 离线 golden + regression 子集
每日/nightly → 全量离线 + 近线回放
发版        → 全量 + 小流量在线评估（canary）
```

### 5.4 如何做 Badcase

页面退场后，**工单系统是 badcase 的系统 of record**，PG 表保留为副本或数据源。
固定七步流水线：

```text
① 入口        ② 去重/分级     ③ 归因          ④ 复现
产品内反馈      按 trace/意图     category→层      trace 深链 + 输入快照
客服/告警       合并同类项        + 责任模块       + Checkpoint 快照
在线评估判坏                                        ↓
                                              ⑤ 修复
                                              ⑥ 回归用例（进入 regression split）
                                              ⑦ 验证 + 关闭
```

硬约束：

- **没有回归用例不允许关单**——这是 badcase 不复发的唯一保证；
- 工单必须带 `trace_id`，否则退回补充，不可复现的反馈没有价值；
- 根因分类固定（提示词 / 槽位 / 检索 / 政策 / 工具 / 审批 / 编排），与评测 suite 对齐；
- SLA：P0（资金/合规）1 天定级，P1 一周修复，P2 进入季度迭代。

质量指标：每千任务 badcase 率、平均定级时长、平均修复时长、**回归逃逸率**（修过又复发）、
重开率。这些比「open 数量」更能反映闭环健康度。

自动化只在两端：创建工单时从 trace 自动填充 `user_input/expected/actual`；
关单时 webhook 校验「用例已加入数据集且 CI 已通过」。中间归因与写用例保留人工。

### 5.5 如何做验收：证据包

页面退场后，验收不再靠人工点页面对照，而是产出可审计的证据包：

| 验收项 | 证据形式 | 工具 |
|---|---|---|
| 功能链路 | e2e 测试报告 + 用例 ID | pytest / Playwright |
| 协议与错误码 | 契约测试结果 | 现有测试 |
| 性能/容量 | 压测报告（P95、错误率、饱和点） | k6 / Locust |
| 韧性 | 混沌演练记录（停 PG/Redis/worker） | `X-Mock-Fault` + compose 操作日志 |
| SLO | 观察窗口内燃烧率 < 1、错误预算剩余 | Grafana 快照 + PromQL 链接 |
| 观测完备性 | span 覆盖率、日志字段完整率、告警演练 | Trace 后端 + ES + 告警记录 |
| 质量门禁 | `make eval --json` 报告 | CI artifact |
| 安全 | 跨租户 403、限流 429、JWT 拒绝记录 | 现有用例 + CI |

验收记录必须写明：**commit SHA、dataset_version、prompt/model 版本、compose profile、
观察窗口**，保证半年后仍可复现「当时为什么算通过」。

### 5.6 迁移路径与退出条件

| 阶段 | 动作 | 退出条件 |
|---|---|---|
| 1. 双跑 | 保留控制台；修 Trace 后端；日志结构化；导出业务指标 | 外部 Trace UI 能看到完整调用树；Kibana 能按 `trace_id` 字段精确查询 |
| 2. 切读路径 | 业务状态迁到产品后台；badcase 迁到工单；三块看板补全 | 排障、运营、审批三个角色都不再需要 8081 的观测页 |
| 3. 退役视图 | 删除 `/overview`、`/flow`、`/trace` 的观测视图 | 观测、评测、badcase、验收四件事可由外部系统独立支撑 |

第 3 步只删视图：`spans` 投影、`badcases` 表和对应 API 继续作为业务数据保留。

### 5.7 当前缺口与优先级

1. **Trace 后端可用性**——修 SkyWalking 或引入 Tempo；这是弃页面后的头号阻塞项。
2. **日志结构化**——Collector 增加 `json_parser`。
3. **业务 KPI 导出**——任务状态、审批时延、恢复成功率、badcase 数进入 Prometheus
   或 Grafana PostgreSQL 数据源。
4. **`X-Trace-Id` 回传**——让用户与客服能提供 trace。
5. **评测数据集版本化与拆分**——`dataset_version`、`split`、`source_trace_id`。
6. **SLO 与燃烧率告警**——在现有阈值规则之上增加记录规则。
7. **badcase 与工单系统打通**——系统 of record 外移，PG 表做副本。

---

## 6. 已知限制（阅读本文时需要知道）

- **Kibana 字段未结构化**：应用 JSON 在 `body.text` 内，只能全文检索；后续可在 Collector filelog 增加 `json_parser` 提升为结构化字段。
- **SkyWalking 服务目录为空**：外部栈 11.0.0 的已知限制，只用于确认原始 span 到达。
- **badcase 导出是人工的**：没有自动把 `badcases` 表转成 `badcase_cases.jsonl` 的脚本。
- **评测集离线**：不覆盖真实模型与真实向量库；live 质量依赖 `prompt` suite 录制。
- **控制台默认身份**：概览页查询 badcase 固定使用 mock 管理员 `u002`，属于演示简化。
- **Langfuse 端口**：验收环境为 `13002`；`docs/runbooks/observability.md` 中的 `3030` 是 worker 端口，浏览 UI 请用 `13002`。
