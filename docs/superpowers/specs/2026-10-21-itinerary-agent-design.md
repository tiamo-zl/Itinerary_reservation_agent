# 差旅预订 Agent 设计文档

- 日期：2026-10-21
- 状态：待评审
- 目标形态：生产级架构的学习 demo（本地运行、外部系统模拟）

## 1. 背景与目标

`readme.md` 描述了一个七层架构的差旅对话助手：员工用自然语言提出差旅需求，Agent 串联行程咨询、签证查询、行程规划、机票酒店查询、差标校验、审批与下单。

现有开源项目大多面向 C 端旅行规划，几乎没有覆盖企业差旅的差标合规、审批链路、多企业制度与任务断点恢复。本项目以这些差异化为重点，做一个**生产级形态的学习 demo**：

- 架构与工程机制按生产标准设计；
- 部署与基础设施降级到本地轻量栈；
- 外部系统（用户、权限、角色、库存、审批、下单、制度文档）全部使用模拟数据；
- 目标是完整演示"一次差旅请求如何跨七层流转"，而不是接入真实业务系统。

## 2. 范围

### 2.1 范围内

主链路：需求理解 → 行程规划 → 机票/酒店查询 → 差标校验 → 审批 → 下单。

关键分支：

- 中途修改目的地或预算；
- 差标超标后的用户确认或特批；
- 审批驳回并重新规划；
- 人在回路确认（方案选择、补充信息）；
- 查询无结果、工具临时失败、暂停/恢复/取消；
- 制度检索降级。

工程能力：

- LangGraph 任务状态机与 Checkpoint 断点恢复；
- 工具注册、风险分级、写操作幂等与准入；
- 统一模型网关（聊天与 embedding）；
- 制度结构化检索（条款树、引用图、表格）与三层记忆；
- 规则化差标校验与审批闸门；
- TraceID 贯穿七层与纵向链路回放；
- 端到端测试与可重复的演示场景。

### 2.2 范围外

- 接入真实机票/酒店/审批/下单系统；
- 生产级身份认证、多地域部署、高可用与容量规划；
- 通用 BPM/审批流引擎；
- 完整前端应用（只提供最小 Web 聊天页与 CLI）；
- 计费、结算、发票、报销；
- 移动端。

## 3. 设计原则

1. **逻辑七层、物理单体**：七层作为包与接口隔离，运行在单个 FastAPI 进程内；需要时可把任一层拆成独立服务。
2. **依赖单向**：外层依赖内层接口，内层不反向依赖外层；具体实现只在组合根装配。
3. **两个唯一出口**：所有大模型/embedding 调用只经过模型网关；所有外部业务系统只经过工具层。
4. **状态最小化**：图状态只保存摘要、决策与引用 ID；制度原文、聊天全文、完整库存数据不进入状态。
5. **控制确定性**：差标、审批、下单准入由代码判定；差标规则由制度表格编译、审核后启用，模型只负责理解与规划。
6. **一切可模拟**：外部依赖都有 mock 实现，测试默认不访问真实网络。
7. **全链路可观测**：trace_id 从网关进入，贯穿图节点、工具、知识、模型、控制。
8. **中间件由使用者安装**：项目只声明依赖与配置，不自动下载安装成熟组件。
9. **制度不是普通文档**：条款层级、引用/例外关系、表格和版本必须结构化；判定靠规则，解释靠检索。

## 4. 总体架构

### 4.1 运行时拓扑

```text
Browser / CLI
     │  HTTP + SSE
     ▼
┌─────────────────────── FastAPI 进程 ───────────────────────┐
│  api/（L1 接入网关）                                         │
│    trace_id · 鉴权 · 校验 · PII · 限流 · SSE 封装            │
│                         │                                    │
│                         ▼                                    │
│  orchestration/（L2）LangGraph 图 + SQLite（Checkpoint/制度关系/记忆/Trace）│
│     │         │            │            │                    │
│     ▼         ▼            ▼            ▼                    │
│  tools/    knowledge/  model_gateway/  control/              │
│   (L3)       (L4)          (L5)          (L6)                │
│     │         │            │                                 │
│     ▼         ▼            ▼                                 │
│  adapters/mock（用户/权限/库存/审批/下单）                    │
│  observability/（L7）贯穿所有调用，输出 SQLite / JSONL        │
└──────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
  Milvus 127.0.0.1:19530         OpenAI 兼容 API
  （制度向量库，独立服务）         ├─ DeepSeek（聊天）
                                  └─ DashScope（embedding）
```

### 4.2 包结构

```text
src/itinerary_agent/
├── api/               # L1 接入网关：路由、中间件、SSE、错误封装
├── application/       # 用例服务：查询/反馈/权限校验/事务边界
│   ├── ports.py       # 仓储与外部依赖 Protocol
│   ├── access.py      # 租户/角色/归属校验
│   ├── trace_queries.py
│   ├── conversation_queries.py
│   ├── approval_queries.py
│   ├── task_queries.py
│   └── feedback_service.py
├── orchestration/     # L2 编排：graph、state、nodes、subgraphs、checkpoint、service
├── tools/             # L3 工具：注册表、契约、风险分级、内置工具、MCP 适配
├── knowledge/         # L4 制度解析、条款图、混合检索、规则编译、记忆
├── model_gateway/     # L5 模型网关：聊天与 embedding、分档路由、重试、成本统计
├── control/           # L6 控制：差标求值、动作准入、审批闸门、审计
├── observability/     # L7 可观测：span 工具、层标记、exporter、回放查询
├── domain/            # 共享领域模型
├── adapters/          # 外部系统接口 + mock 实现
│   ├── interfaces.py
│   └── mock/
├── infra/             # 配置、SQLite、Milvus、依赖装配（组合根）
│   └── repositories/  # 仓储实现：SQL 只出现在这里
└── main.py
```

`domain/` 是共享模型；`application/` 是用例编排与权限边界；`infra/` 是唯一允许 import 具体适配器、mock 和仓储实现的组合根。

### 4.3 依赖规则

```text
api → application → {orchestration 接口, domain}
api → Orchestrator（对话/恢复用例）
application → ports（仓储 Protocol）← infra/repositories
orchestration → {tools, knowledge, model_gateway, control}
tools → adapters
knowledge → EmbeddingPort（domain）+ adapters（文档源）
control → domain
adapters → domain
observability ← 所有层（只被依赖，不反向依赖业务）
infra → 所有具体实现 + application（装配）
```

硬性约束：

- `api` 只依赖应用服务与 `Orchestrator` 接口，不知道 LangGraph 的存在；
- **`api` 中禁止出现 SQL，也不直接访问 `container.db`**；
- **仓储实现只在 `infra/repositories/`，SQL 不泄漏到应用服务和控制器**；
- **租户/角色/任务归属校验在应用服务完成，不在每个 handler 重复实现**；
- 写用例的事务边界由应用服务控制；
- `orchestration` 依赖工具/知识/模型/控制的接口，不 import 具体实现或 mock；
- 任何节点不得直接调用模型 SDK 或外部业务接口；
- 知识层返回结构化 context pack（条款/表格/引用）与引用 ID，不返回整篇文档；
- 知识层只依赖 `EmbeddingPort`，不直接依赖模型网关；由 `infra` 完成绑定；
- 控制层不做业务查询，只依据输入与规则判断；
- `infra` 负责装配，是唯一允许出现具体类名的位置。

### 4.4 关键接口

```python
class Orchestrator(Protocol):
    async def start_turn(self, ctx: RequestContext, message: str) -> AsyncIterator[Event]: ...
    async def resume(self, ctx: RequestContext, task_id: str, decision: Decision) -> AsyncIterator[Event]: ...
    async def get_task(self, ctx: RequestContext, task_id: str) -> TaskView: ...

class ToolService(Protocol):
    def list_tools(self, ctx: RequestContext, task_type: str) -> list[ToolSpec]: ...
    async def invoke(self, ctx: RequestContext, name: str, args: dict) -> ToolResult: ...

class ModelGateway(Protocol):
    async def complete(self, ctx: CallContext, messages: list[Message],
                       tier: ModelTier, response_schema: dict | None = None) -> Completion: ...
    async def stream(self, ctx: CallContext, messages: list[Message],
                     tier: ModelTier) -> AsyncIterator[Token]: ...
    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]: ...

class EmbeddingPort(Protocol):
    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]: ...

class PolicyFilters(BaseModel):
    city_tier: int | None = None
    employee_level: str | None = None
    effective_date: str | None = None

class PolicyClause(BaseModel):
    clause_id: str
    path: str
    title: str
    text: str
    clause_type: str
    policy_version: str
    table_id: str | None = None
    refs: list[str] = Field(default_factory=list)

class PolicyTable(BaseModel):
    table_id: str
    source_clause_id: str
    columns: list[str]
    rows: list[dict]

class PolicyContext(BaseModel):
    clauses: list[PolicyClause]
    tables: list[PolicyTable]
    citations: list[str]
    policy_version: str
    degraded: bool = False
    insufficient: bool = False
    trace: dict = Field(default_factory=dict)

class KnowledgeService(Protocol):
    async def search_policy(self, ctx: RequestContext, query: str,
                            filters: PolicyFilters | None = None) -> PolicyContext: ...
    async def get_clause(self, ctx: RequestContext, clause_id: str) -> PolicyClause: ...
    async def get_table(self, ctx: RequestContext, table_id: str) -> PolicyTable: ...
    async def get_memories(self, ctx: RequestContext, kinds: list[str]) -> list[UserMemory]: ...
    async def upsert_memory(self, ctx: RequestContext, memory: UserMemory) -> None: ...

class TaskSnapshot(BaseModel):
    task_id: str
    status: TaskStatus
    revision: int
    policy_passed: bool | None
    approval_status: ApprovalStatus | None
    confirmed: bool

class ControlService(Protocol):
    def check_policy(self, request: TripRequest, options: SearchResults,
                     user: UserProfile, rules: PolicyRules) -> PolicyResult: ...
    def guard(self, ctx: RequestContext, action: str, snapshot: TaskSnapshot) -> GuardResult: ...
```

`guard` 只接收窄化的 `TaskSnapshot`，不依赖编排层的 `TravelTaskState`，保证控制层不反向依赖编排层。`KnowledgeService` 通过 `EmbeddingPort` 生成入库与查询向量，由 `infra` 绑定到 `ModelGateway.embed`，保证 embedding 仍然只有一个出口。

### 4.5 组合根

`infra/container.py` 根据配置组装：

- `llm_provider`: `deepseek`（默认）或任意 OpenAI 兼容端点；
- `embedding_provider`: `dashscope`（默认）；
- `vector_store`: `milvus`；
- `adapters`: `mock`（默认）；
- `trace_exporter`: `sqlite`（默认）。

切换实现只改配置，不改业务代码。

### 4.6 接入层、应用服务与仓储层

生产级项目不应在 HTTP handler 里直接拼 SQL。读写路径统一按四层职责组织：

| 角色 | 位置 | 职责 | 禁止 |
|---|---|---|---|
| Controller | `api/` | 解析 HTTP/SSE、构造 `RequestContext`、DTO 映射、错误映射 | SQL、业务规则、事务 |
| Application Service | `application/` | 用例编排、租户/角色/归属校验、组合多个仓储、事务边界 | 依赖 FastAPI、直接构造 HTTP 响应 |
| Port | `application/ports.py` | 仓储/外部依赖的 `Protocol` | 具体实现 |
| Repository | `infra/repositories/` | SQL 与存储细节、查询结果转 DTO | 业务规则、权限判断 |

读路径允许 **Query Service（CQRS-lite）**：不强制构造完整 DDD 聚合，但查询组合、权限过滤和 DTO 转换必须在应用服务中完成。写路径由应用服务控制事务。

`trace_json` 的目标写法：

```python
# application/trace_queries.py
class TraceQueryService:
    def __init__(self, trace_repo: TraceRepository,
                 task_repo: TaskRepository):
        self.trace_repo = trace_repo
        self.task_repo = task_repo

    async def get_trace(self, ctx: RequestContext, trace_id: str) -> TraceDetail:
        task = await self.task_repo.find_by_trace(ctx.tenant_id, trace_id)
        if task is None:
            raise NotFound("trace")
        if not can_view_task(ctx, task):
            raise Forbidden("trace")
        spans = await self.trace_repo.load_spans(ctx.tenant_id, trace_id)
        return TraceDetail(trace_id=trace_id, task=task, spans=build_tree(spans))
```

```python
# infra/repositories/trace_repository.py
class SqliteTraceRepository:
    def __init__(self, db: Database):
        self.db = db

    async def load_spans(self, tenant_id: str, trace_id: str):
        # 只有这里允许出现 traces/spans 的 SQL 和列名
        ...
```

```python
# api/routes.py
@router.get("/traces/{trace_id}")
async def trace_json(trace_id: str, request: Request):
    ctx = build_context(request)
    return await container.trace_queries.get_trace(ctx, trace_id)
```

验收约束：

- 对 `api/` 做静态检查，不允许出现 `container.db`、`SELECT`、`INSERT`、`UPDATE`、`DELETE`；
- 应用服务只依赖 `Protocol`，可注入 fake repository 做单元测试；
- Repository 返回查询 DTO，不把 ORM/SQLite Row 直接传到 HTTP；
- 权限错误使用应用层异常，由控制器统一映射为 403/404；
- 读写都按 `tenant_id` 隔离，管理员跨租户查看也需要显式授权。

## 5. 领域模型与任务状态机

### 5.1 状态定义

| 状态 | 含义 | 可恢复 |
|---|---|---|
| `PLANNING` | 需求理解、任务拆解、候选方案生成 | 是 |
| `EXECUTING` | 查询、差标校验、提交审批、下单等执行中 | 是 |
| `WAITING_HUMAN` | 等待用户确认：方案选择、超标准、补充信息、驳回后修改 | 是 |
| `WAITING_APPROVAL` | 等待审批结果 | 是 |
| `PAUSED` | 用户主动暂停 | 是 |
| `COMPLETED` | 下单成功或正常结束 | 否 |
| `CANCELLED` | 用户取消或等待超时 | 否 |
| `FAILED` | 不可恢复错误 | 否 |

### 5.2 状态迁移

```text
PLANNING ──▶ EXECUTING ──▶ WAITING_HUMAN
                 │               │
                 │               └──resume──▶ EXECUTING / PLANNING
                 ├──需审批──▶ WAITING_APPROVAL
                 │               ├──approved──▶ EXECUTING
                 │               └──rejected──▶ WAITING_HUMAN
                 └──下单成功──▶ COMPLETED

任意非终态 ──▶ PAUSED ──resume──▶ 原状态
任意非终态 ──▶ CANCELLED
任意非终态 ──▶ FAILED
```

约束：

- 终态不可恢复；需要继续时应创建新任务。
- 同一任务同一时刻最多一个待处理的人类决策或审批。
- `WAITING_*` 默认 24 小时超时，超时转 `CANCELLED` 并记录原因。

### 5.3 LangGraph 图

```text
understand ─▶ plan ─▶ dispatch ─┬─▶ search_subgraph（机票/酒店并行）
                                 ├─▶ check_policy
                                 └─▶ request_approval
                                             │
                                             ▼
                            confirm ─▶ book ─▶ finalize
                                │
                                └─ interrupt → WAITING_HUMAN
```

节点职责：

| 节点 | 职责 | 是否调模型 |
|---|---|---|
| `understand` | 自然语言 → `TripRequest`；缺失槽位进入追问 | 是（light） |
| `plan` | 生成 `SubTask[]`，加载用户长期偏好 | 是（reasoning） |
| `dispatch` | 根据状态决定下一步 | 否 |
| `search_subgraph` | 调用机票/酒店查询工具，并行 | 否 |
| `check_policy` | 调用控制层求值 | 否 |
| `request_approval` | 提交审批并中断等待 | 否 |
| `confirm` | 需要用户确认时 `interrupt()` | 否 |
| `book` | 执行写操作 | 否 |
| `finalize` | 汇总结果、写长期记忆、结束 | 是（standard，可选摘要） |

### 5.4 Checkpoint 与恢复

- `thread_id = task_id`，使用 `AsyncSqliteSaver`；
- 状态含 `schema_version`；
- `interrupt()` 时保存现场并返回中断事件；
- `resume(task_id, decision)` 通过 `Command(resume=...)` 从断点继续，不重跑已完成节点；
- 恢复前校验：任务存在、状态允许、`decision` 合法、当前用户有权限；
- 审批等待同样使用中断；mock 审批结果通过回调或轮询恢复。

### 5.5 中途修改与 revision

- 状态维护 `revision` 与 `request` 中的约束字段（目的地、日期、预算等）；
- `WAITING_HUMAN` / `PAUSED` 时可直接提交修改；`EXECUTING` 时写入 `pending_amendment`，在下一个节点边界应用；
- 应用修改后：`revision += 1`，清空 `options`、`policy_result`、`policy_refs`、`approval`、`selected`、`confirmed`，回到 `plan`；
- 审批和下单都校验 `revision` 与提交时一致。

### 5.6 幂等与副作用

- 写操作幂等键：`task_id:step_id:revision`；
- mock 外部系统维护已处理键集合；
- 下单前依次校验：差标通过/豁免、审批通过（如需要）、用户已确认、revision 未变、幂等键未使用。

### 5.7 状态结构

```python
class TravelTaskState(TypedDict):
    task_id: str
    trace_id: str
    tenant_id: str
    user_id: str
    status: TaskStatus
    revision: int
    request: TripRequest
    plan: list[SubTask]
    options: SearchResults
    selected: SelectedOptions
    confirmed: bool
    policy_result: PolicyResult | None
    policy_refs: list[str]
    approval: ApprovalRef | None
    pending_human: HumanRequest | None
    pending_amendment: TripRequest | None
    error: ErrorInfo | None
    schema_version: int
```

完整对话历史不入图状态，存放在记忆层，状态中只保留摘要与引用 ID。

## 6. 数据流与工具契约

### 6.1 正常链路

```text
用户消息
  → [L1] 鉴权、trace_id、PII 过滤、校验
  → [L2] understand（light 模型）→ TripRequest
  → [L2] plan（reasoning 模型）→ SubTask[]
  → 需要制度依据时：[L4] knowledge.search_policy → context pack（条款/表格/引用）
  → [L3] search_flights / search_hotels（并行）
  → [L6] check_policy（使用编译后的差标规则，不依赖 RAG）
  → 通过：confirm（interrupt）→ book → finalize
  → 需审批：submit_approval → WAITING_APPROVAL → approved → confirm → book
  → 驳回：WAITING_HUMAN → 用户修改 → revision++ → plan
```

### 6.2 工具契约

```python
class ToolSpec(BaseModel):
    name: str
    description: str
    side_effect: Literal["read", "write"]
    risk: Literal["low", "medium", "high"]
    required_scopes: list[str]
    idempotent: bool
    timeout_ms: int
    input_schema: dict
    output_schema: dict

class ToolResult(BaseModel):
    ok: bool
    data: dict | None
    error: ToolError | None   # code, message, retryable
    trace_id: str
```

调用管线（编排层与工具层协作）：

1. 编排层按 `input_schema` 校验参数；
2. 编排层调用 `control.guard` 判断权限、风险与前置状态；
3. `ToolService` 对写操作检查幂等键；
4. 开启 span（`layer=tools`，含工具名与风险等级）；
5. 调用 adapter；
6. 输出归一化与脱敏；
7. 写审计记录。

`guard` 在编排层执行，`ToolService` 不依赖控制层，保持依赖方向不变。

### 6.3 工具清单

| 工具 | 类型 | 风险 | 输入要点 | 输出要点 |
|---|---|---|---|---|
| `search_flights` | read | low | 出发地、目的地、日期、舱位、人数 | `FlightOption[]` |
| `search_hotels` | read | low | 城市、入住/离店、区域、预算 | `HotelOption[]` |
| `submit_approval` | write | high | task_id、revision、方案快照、差标结果 | `approval_id`、状态 |
| `get_approval_status` | read | low | approval_id | 状态与意见 |
| `book_flight` | write | high | 选项 ID、乘机人、approval_id、幂等键 | `booking_id`、出票状态 |
| `book_hotel` | write | high | 选项 ID、入住人、approval_id、幂等键 | `booking_id`、确认号 |
| `get_user_profile` | read | low | 无 | 职级、部门、常旅客信息 |
| `get_policy_rules` | read | low | tenant_id、职级、城市等级 | 适用规则摘要（用于向用户解释） |
| `get_visa_requirements` | read | low | 国籍、目的地 | 签证要求摘要 |

工具只返回结构化摘要与引用 ID；完整数据由适配层按 ID 读取，不进入图状态。

### 6.4 差标校验契约

差标由控制层的确定性函数计算，不作为模型可选择的工具：

```python
def check_policy(request: TripRequest, options: SearchResults,
                 user: UserProfile, rules: PolicyRules) -> PolicyResult
```

```python
class PolicyResult(BaseModel):
    passed: bool
    requires_approval: bool
    violations: list[Violation]
    policy_version: str

class Violation(BaseModel):
    rule_id: str
    category: Literal["flight", "hotel", "date", "other"]
    severity: Literal["block", "warn"]
    message: str
    limit: float | None
    actual: float | None
    source_clause_id: str | None = None
```

模型可调用只读的规则解释能力来向用户说明"为什么超标"，但不能改变判定。`source_clause_id` 用于把规则判定关联回制度条款，回答时给出依据。

### 6.5 错误与重试

| 错误来源 | 处理 |
|---|---|
| 参数缺失/格式错误 | 回 `understand` 追问 |
| 查询无结果 | 回 `plan` 放宽条件或提示用户 |
| 差标阻断 | `WAITING_HUMAN`，允许修改；规则允许时走审批 |
| 审批驳回 | 带回原因，回 `plan`，`revision++` |
| 工具临时失败 | 工具层重试；仍失败则提示或 `FAILED` |
| 模型 429/超时 | 模型网关重试/降级；不可恢复则 `FAILED` |
| 状态非法 | 控制层拒绝，记录审计 |

## 7. 模型网关

### 7.1 职责

所有聊天与 embedding 调用的唯一出口。业务代码只描述能力，不关心厂商。

```python
class CallContext(BaseModel):
    trace_id: str
    task_id: str | None
    tenant_id: str
    purpose: Literal["understand", "plan", "explain", "summarize", "classify", "embed"]
    prompt_version: str
```

### 7.2 分档路由

档位与模型别名在 YAML 配置中定义，不在代码中写死：

| 档位 | 用途 | 配置示例 |
|---|---|---|
| `light` | 意图识别、槽位抽取、分类 | DeepSeek 轻量对话模型 |
| `standard` | 摘要、回复润色、制度解释 | DeepSeek 中等模型 |
| `reasoning` | 行程规划、方案比较、驳回原因分析 | DeepSeek 推理模型 |

每档可配置备用模型。真实模型 ID、`base_url`、`api_key` 由部署配置提供。

### 7.3 Embedding

- 供应商：阿里云百炼 DashScope，OpenAI 兼容模式；
- 模型：`qwen3.7-text-embedding-flash`；
- 维度：1024（可选 768/512/256，建库前确定）；
- base_url：默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`，可改为业务空间专属地址；
- 单批最多 20 条输入，网关负责分批；
- 只使用 dense 向量；稀疏向量需要原生 DashScope API，本项目不使用；
- 按“条款”而不是章节做 embedding：文本 = 文档路径 + 标题 + 正文；
- 表格行单独结构化存储，检索时按 `table_id` 取回并过滤，不把表格切碎；
- 检索采用关键词（FTS5）+ 向量混合召回，再做引用图扩展；
- 模型分区域上架，默认使用北京地域。

### 7.4 横切能力

- **重试与降级**：429/5xx 指数退避，档位备用模型；
- **超时与熔断**：单次调用超时，连续失败熔断；
- **结构化输出**：JSON schema + Pydantic 校验，失败时一次修复重试；
- **缓存**：确定性调用（分类、槽位抽取、制度解释）可按 `model + messages + schema` 哈希缓存；规划类默认不缓存；
- **成本统计**：记录 tokens、估算费用、耗时，按 task/tenant/purpose 汇总到 SQLite；
- **脱敏**：API Key 与完整 PII 不写日志；记录 `prompt_version` 与模型标识。

### 7.5 边界

模型网关不执行业务动作，也不决定工具调用。模型输出结构化意图或计划，工具由编排层选择并经工具层执行。

## 8. 知识与记忆

制度不是普通文档：条款有层级、跨引用、例外、表格和版本，差标判定又必须确定。因此知识层分成两条路径：

- **制度解释/问答**：结构化条款树 + 混合检索 + 引用图扩展，返回带引用的 context pack；
- **差标判定**：从制度表格编译成结构化规则，由控制层确定性执行。

RAG 不承担合规判定，规则不负责自然语言解释；两者通过 `source_clause_id` 关联。

### 8.1 制度结构化模型

```text
PolicyDocument
└── Chapter（章）
    └── Article（条）
        └── Clause（款/项）
            ├── parent_id
            ├── path                 # travel-policy/ch3/art12/cl2
            ├── refs[]               # 引用条款/附表 ID
            ├── exceptions[]         # 例外条款 ID
            ├── definitions[]        # 适用定义 ID
            ├── table_id             # 该条包含的表格
            └── effective_from/to
```

表格单独建模（`PolicyTable`，定义见 4.4），不做文本切分；每一行保留列名与来源条款。

引用关系单独存边：

| 关系 | 含义 |
|---|---|
| `references` | 条款引用另一条款或附表 |
| `exception_to` | 例外条款作用于主条款 |
| `defines` | 定义条款解释术语 |
| `amends` | 修订条款修改目标条款 |
| `supersedes` | 新版本替代旧版本 |

### 8.2 入库管线

```text
企业制度 PDF
  → 文档解析（优先 Docling，demo 可用 PyMuPDF）
  → 结构抽取：标题、条款编号、表格、附录
  → 条款树 + 表格 + 引用/例外/定义关系
  → 引用解析与校验 → 低置信度进入人工校对队列
  → 条款级 embedding（文本 = 路径 + 标题 + 正文）
  → 写入 Milvus（向量）与 SQLite（结构/关系/表格/FTS5）
  → 规则编译（差标表格 → 规则，需人工审核后启用）
```

约束：

- **不 drop、不覆盖已有数据**；新制度版本以新 `policy_version` 写入；
- 每个条款必须能追溯到文档、页码和版本；
- 跨引用解析失败的条款不进入可用状态，进入 `policy_ingest_reviews`；
- 表格必须保留表头与行语义，合并单元格在解析时展开；
- 规则编译结果必须校验来源条款与表格行，审核通过后才生效。

### 8.3 存储

**Milvus**：`itinerary_policy_clauses_v1`，一条款一向量。

| 字段 | 类型 | 说明 |
|---|---|---|
| `clause_id` | VARCHAR(64) | 主键，稳定 ID |
| `tenant_id` | VARCHAR(64) | partition key（schema 中标记） |
| `doc_id` | VARCHAR(64) | 文档 ID |
| `policy_version` | VARCHAR(32) | 制度版本 |
| `clause_type` | VARCHAR(32) | chapter / article / clause / table / definition |
| `path` | VARCHAR(512) | 文档路径 |
| `parent_id` | VARCHAR(64) | 父条款 |
| `title` | VARCHAR(256) | 条款标题 |
| `text` | VARCHAR(8192) | 条款正文 |
| `embedding` | FLOAT_VECTOR(1024) | 向量 |
| `table_id` | VARCHAR(64) | 关联表格，可空 |
| `refs` | JSON | 引用条款 ID 列表 |
| `effective_from` | VARCHAR(10) | 生效日期 |
| `effective_to` | VARCHAR(10) | 失效日期，可空 |

索引：HNSW，COSINE。检索过滤：`tenant_id` + `policy_version` + 生效日期。

**SQLite**：关系、结构、表格与关键词检索。

```text
policy_documents(doc_id, tenant_id, title, policy_version, effective_from, effective_to)
policy_clauses(clause_id, parent_id, doc_id, path, clause_type, title, text, order_no)
policy_edges(source_id, relation, target_id)
policy_tables(table_id, source_clause_id, columns_json, rows_json)
policy_definitions(definition_id, term, text, source_clause_id)
policy_rules(rule_id, tenant_id, category, match_json, limit, severity,
             allow_approval, source_clause_id, policy_version, effective_from, effective_to)
policy_ingest_reviews(review_id, clause_id, reason, status, created_at)
policy_fts(clause_id, title, text)    -- SQLite FTS5
```

### 8.4 检索流程

```text
用户问题
  → 查询理解：费用类型、城市等级、职级、日期、意图
  → 混合召回：FTS5 关键词 + Milvus 向量
  → RRF 融合，取前 8 个条款作为种子
  → 图扩展 1–2 跳：
       祖先（适用范围）、引用条款、例外条款、定义、同章节兄弟
  → 表格解析：按 table_id 取结构化行，按用户职级/城市过滤
  → 按文档顺序组装 context pack（含 clause_id 引用）
  → 置信度判断：关键条款/表格缺失时标记 insufficient
```

检索返回 4.4 定义的 `PolicyContext`：条款、表格、引用 ID、版本、`degraded`、`insufficient` 与检索 trace。

规则：

- 图状态只保存 `policy_refs` 与摘要，不保存整段制度；
- 回答必须引用 `clause_id` 对应的文档/条款；
- 检索不足时明确回答"制度未明确/无法确认"，不得让模型补全；
- Milvus 或 embedding 不可用时返回 `degraded=true`，规则引擎照常工作；
- 没有命中关键条款或表格时返回 `insufficient=true`，进入人工确认或追问。

### 8.5 差标规则编译

制度中的标准表格（职级 × 城市等级 × 金额）编译为结构化规则：

```yaml
- id: hotel-standard-L1-L2
  match: { employee_level: ["L1", "L2"], city_tier: [1, 2] }
  category: hotel
  limit: 500
  severity: block
  allow_approval: true
  source_clause_id: travel-policy/ch3/art12
  policy_version: "2026.1"
  effective_from: "2026-01-01"
```

编译流程：

1. 从表格行生成候选规则；
2. 校验：来源条款存在、表格行列完整、金额/职级/城市映射正确；
3. 人工审核后启用；
4. 制度版本更新时生成新规则版本，旧规则标记失效；
5. 控制层只使用已启用规则；回答溢出原因时引用 `source_clause_id`。

### 8.6 索引与版本

- collection 名带版本：`itinerary_policy_clauses_v1`；
- 元数据记录 `embedding_model`、`dimensions`、`parser_version`、`policy_version`；
- 更换 embedding 模型或维度时新建 collection 并重建，不在旧 collection 中混写；
- 检索默认只取当前有效版本；`supersedes` 关系用于展示版本差异；
- 重新入库不修改历史条款，追加新版本。

### 8.7 三层记忆

| 记忆类型 | 存放位置 | 生命周期 | 进入图状态的内容 |
|---|---|---|---|
| 会话短期记忆 | SQLite `messages` 表 | 会话级 | 最近 N 轮摘要 + 引用 ID |
| 工作记忆 | LangGraph Checkpoint | 任务级 | 任务状态本身 |
| 用户长期偏好 | SQLite `user_memories` 表 | 跨会话，默认 180 天 | 检索到的偏好摘要 |

```python
class UserMemory(BaseModel):
    memory_id: str
    tenant_id: str
    user_id: str
    kind: Literal["preference", "habit", "constraint"]
    key: str
    value: str
    confidence: float
    source_task_id: str | None
    updated_at: datetime
    expires_at: datetime | None
```

写入规则：

- 任务完成或用户明确表达偏好时写入；
- 低置信度不覆盖高置信度；
- 不写敏感信息；
- 支持按用户查询与删除。

读取时机：`plan` 前加载相关偏好作为上下文，不把全部记忆放入 prompt。

### 8.8 评估

用金标问题集验证，而不只看回答是否通顺：

| 类型 | 示例 | 指标 |
|---|---|---|
| 跨条款 | "住宿标准在哪里？" | 是否召回被引用条款与附表 |
| 例外 | "超标但有紧急会议能否报销？" | 是否召回例外条款并正确适用 |
| 表格 | "L2 去二线城市住 600 是否超标？" | 是否取到正确表格行与金额 |
| 版本 | "2025 与 2026 版住宿标准差异？" | 是否区分版本与生效日期 |
| 多跳 | "审批通过后超标部分谁承担？" | 是否串联引用链 |
| 无答案 | "制度是否覆盖私人行程？" | 是否正确返回 insufficient |

指标：条款召回率、引用准确率、表格行准确率、答案忠实度、`insufficient` 判定准确率。

### 8.9 Demo 与生产取舍

| 能力 | Demo | 生产 |
|---|---|---|
| PDF 解析 | PyMuPDF + 编号规则 | Docling / OCR + 版面分析 |
| 结构抽取 | 规则 + 人工校对小样本 | LLM 辅助抽取 + 人工审核队列 |
| 关键词检索 | SQLite FTS5 | Elasticsearch / OpenSearch |
| 图扩展 | SQLite `policy_edges`，1–2 跳 | 图数据库或图服务 |
| 重排 | RRF 融合 | Cross-encoder reranker |
| 规则编译 | 手工 YAML + 来源校验 | 自动抽取 + 规则治理流程 |
| 版本管理 | policy_version + 生效日期 | 版本对比、修订追踪、回滚 |

demo 不引入 Neo4j；SQLite 关系表足以验证“强关联检索”的机制。

## 9. 控制层

### 9.1 差标规则

```yaml
version: "2026.1"
tenant_id: demo-company

defaults:
  flight: { cabin: economy, max_price: 2000 }
  hotel:  { max_price_per_night: 600 }

rules:
  - id: hotel-standard-L1-L2
    match: { employee_level: ["L1", "L2"], city_tier: [1, 2] }
    category: hotel
    limit: 500
    severity: block
    allow_approval: true
    source_clause_id: travel-policy/ch3/art12
  - id: flight-cabin-L1
    match: { employee_level: ["L1"] }
    category: flight
    constraint: { cabin: ["economy"] }
    severity: warn
    source_clause_id: travel-policy/ch2/art06
```

规则由制度表格编译，带 `source_clause_id`；未审核的规则不生效。求值顺序：精确规则 → 默认规则 → 无匹配则拒绝并记录原因。

规则语义：

- `severity: block` + `allow_approval: true`：禁止直订，但允许走审批；
- `severity: block` 且未允许审批：超标准直接拒绝；
- `severity: warn`：仅提示，用户确认后可继续。

失败策略：规则加载失败时写操作一律拒绝（fail-closed），读操作可降级。

### 9.2 动作准入

| 动作 | 前置条件 |
|---|---|
| `search_*` | 已鉴权、租户匹配、具备查询权限 |
| `submit_approval` | 存在 `PolicyResult`、revision 未变、无重复待审批 |
| `book_*` | 差标通过或有效豁免；需审批时已通过；用户已确认；revision 与审批时一致；幂等键未使用 |
| `cancel_task` | 任务属主或审批人 |

```python
class GuardResult(BaseModel):
    allowed: bool
    code: str
    message: str
    required_action: str | None
```

### 9.3 审批闸门

- `check_policy` 产出 `requires_approval`；
- 需要审批时提交并进入 `WAITING_APPROVAL`；
- mock 审批默认 5 秒后自动通过，便于演示主链路；
- 提供手动审批接口，用于演示驳回：驳回附带意见，任务回到 `WAITING_HUMAN`；
- 用户修改后 `revision++`，重新校验与审批；
- demo 由编排服务内的轻量轮询器（每 2 秒检查待审批任务）触发恢复；生产改用审批系统回调。

### 9.4 审计

每次控制决策写入审计表：

```text
decision_id, trace_id, task_id, actor, action,
inputs_hash, rule_ids, policy_version, decision, reason, created_at
```

审计表只追加；敏感字段脱敏后存储。

## 10. 可观测与评估

### 10.1 数据模型

采用 OTel 的 trace/span 结构：

```text
Span
├── trace_id / span_id / parent_span_id
├── name              # gateway.http / orchestration.node.plan / tool.search_flights
├── layer             # gateway|orchestration|tools|knowledge|model|control
├── task_id / tenant_id / user_ref
├── status            # ok|error|blocked
├── start_time / duration_ms
└── attributes        # tool_name, model, tokens, cost, rule_ids, revision ...
```

### 10.2 埋点位置

| 层 | Span |
|---|---|
| 网关 | `gateway.http` |
| 编排 | 每个节点一个 span；中断/恢复单独记录 |
| 工具 | 每次调用一个 span，含风险等级与读写类型 |
| 知识 | 检索 span，含种子数、图扩展条款数、表格命中、`insufficient`、是否降级 |
| 模型 | 每次聊天/embedding 调用，含模型、tokens、成本、prompt_version |
| 控制 | `control.check_policy`、`control.action_guard`，含 rule_ids 与决策 |

### 10.3 存储与视图

- Exporter 写 SQLite：`traces`、`spans`；可选 JSONL 备份；
- 按 `trace_id` 查询，按 `parent_span_id` 建树，按 `start_time` 排序即时间线；
- "纵向七层视图" = 按 `layer` 分组的 span 树；
- 可选接入 Arize Phoenix；不可用不影响主流程。

### 10.4 约束

- 埋点写入失败被吞掉并记告警，不影响业务；
- 默认不存完整 Prompt，只存 hash、版本、token 数；排查时按开关临时开启；
- `user_ref` 为不可逆哈希；
- demo 全量采样；生产改为错误优先或尾采样；
- trace 默认保留 7 天。

### 10.5 评估

- 规则与状态机使用确定性测试；
- RAG 使用小型金标集测召回；
- LLM 输出使用场景回归，可选 Ragas / LLM-as-judge；
- prompt 变更记录 `prompt_version`，便于对比。

## 11. API 与事件

### 11.1 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/chat` | 发起一轮对话，SSE 返回 |
| `POST` | `/tasks/{task_id}/resume` | 提交人类决策或修改，继续任务 |
| `GET` | `/tasks/{task_id}` | 查询任务状态与结果 |
| `GET` | `/traces/{trace_id}` | 查询链路回放 |
| `POST` | `/admin/approvals/{approval_id}` | mock 手动审批（演示驳回） |
| `GET` | `/health` | 健康检查（SQLite、Milvus、模型可达性） |
| `GET` | `/` | 最小 Web 聊天页 |

`/admin/approvals/{approval_id}` 仅在 demo 模式启用，要求管理员角色。

### 11.2 SSE 事件

```text
status    { task_id, status }
progress  { task_id, node, message }
token     { task_id, text }              # 流式回复片段
interrupt { task_id, human_request }     # 需要用户确认/修改
result    { task_id, summary, options }
error     { task_id, code, message }
```

### 11.3 请求上下文

```python
class RequestContext(BaseModel):
    trace_id: str
    tenant_id: str
    user_id: str
    roles: list[str]
    session_id: str
    locale: str = "zh-CN"
```

本地鉴权通过 mock 用户表或请求头映射；生产替换为真实鉴权中间件。

## 12. 安全与合规

- **PII**：网关入参/出参脱敏；trace 与日志不保存完整敏感字段；
- **密钥**：只从环境变量读取；不写入日志、不进入图状态；`.env` 不入库；
- **写操作**：差标、审批、确认、revision、幂等五项校验全部通过才执行；
- **审计**：所有控制决策与写操作留痕；
- **fail-closed**：规则加载失败、状态不明时拒绝写操作；
- **外部数据**：制度 PDF 会发送到阿里云做 embedding；demo 使用模拟文档，接入真实制度前需确认数据驻留与保密要求；
- **提示注入**：制度文本与工具结果视为不可信输入，不直接作为系统指令；模型输出经结构化校验后才进入流程。

## 13. 测试策略

| 层级 | 内容 | 依赖 |
|---|---|---|
| 单元测试 | 差标求值（表驱动）、Guard 条件、状态迁移、参数校验、revision 失效、条款树/引用/表格解析 | 纯 Python + 临时 SQLite |
| 集成测试 | 图执行、interrupt/resume、Checkpoint 恢复、幂等、context pack 与引用、span 产出 | FakeModelGateway、FakeToolService、临时 SQLite |
| 端到端场景 | 下列 12 个分支，使用脚本化模型响应 | 可选 Milvus；默认不调真实 LLM |

端到端场景：

1. 正常链路：查询 → 差标通过 → 确认 → 下单成功；
2. 超标准：阻断 → 修改 → 重新规划 → 审批 → 下单；
3. 审批驳回：带回原因 → 修改 → 再次审批；
4. 中途改预算/目的地：`revision++`，旧结果与审批失效；
5. 查询无结果：放宽条件或提示用户；
6. 暂停/恢复、取消、等待超时；
7. 工具临时失败重试；embedding 不可用时 RAG 降级；
8. 未审批直接下单：Guard 拒绝并留审计；
9. 跨条款问题：正确召回被引用条款与附表；
10. 例外问题：召回到例外条款并正确适用；
11. 表格问题：按职级/城市取到正确表格行与金额；
12. 版本/无答案：区分制度版本；制度未覆盖时返回 `insufficient`，不编造。

工具：`pytest`、`pytest-asyncio`、`httpx`。真实模型冒烟测试标记为 `@pytest.mark.live`，默认不运行。

## 14. 技术选型与依赖

### 14.1 本地 demo

| 能力 | 选型 |
|---|---|
| 运行时 | Python 3.13 + uv |
| Web | FastAPI + uvicorn + sse-starlette |
| 编排 | LangGraph + langgraph-checkpoint-sqlite |
| 模型调用 | LiteLLM / openai 兼容客户端 |
| 聊天模型 | DeepSeek（OpenAI 兼容） |
| Embedding | 阿里云 `qwen3.7-text-embedding-flash`（1024 维） |
| 向量库 | Milvus `127.0.0.1:19530` + pymilvus |
| 结构化存储 | SQLite（条款树、引用边、表格、规则、记忆、trace） |
| 关键词检索 | SQLite FTS5 |
| 检索融合 | RRF（关键词 + 向量） |
| 工具协议 | FastMCP（接口预留，demo 可先直接内置工具） |
| 文档解析 | Docling（优先）/ PyMuPDF（demo 简化） |
| 规则编译 | 制度表格 → SQLite `policy_rules` + 人工审核 |
| 配置 | pydantic-settings |
| 可观测 | OpenTelemetry 数据模型 + SQLite exporter；可选 Arize Phoenix |
| 测试 | pytest + pytest-asyncio + httpx |

### 14.2 需要使用者安装/准备

- Python 3.13 与 uv（已具备）；
- `DEEPSEEK_API_KEY`（或兼容端点）；
- `DASHSCOPE_API_KEY`；
- Milvus 已就绪；
- Python 包由使用者通过 `uv add` 安装；
- 可选：Docling（生产级制度解析）、Arize Phoenix（本地 UI）。

### 14.3 生产替换

| 能力 | 生产方案 |
|---|---|
| 接入网关 | Nginx / APISIX / Kong |
| 鉴权 | Keycloak / Casdoor |
| Checkpoint / 记忆 | PostgreSQL |
| 缓存 / 限流 | Redis |
| 模型网关 | LiteLLM Proxy / Higress / Kong AI Gateway |
| 向量库 | 同一 Milvus 集群（或 pgvector） |
| 制度解析 | Docling / OCR + 版面分析 + 人工校对 |
| 关键词检索 | Elasticsearch / OpenSearch |
| 图扩展 | 图数据库/图服务 + Cross-encoder reranker |
| 可观测 | OTel Collector + Langfuse / Phoenix + Prometheus/Grafana |
| 文档存储 | MinIO / 对象存储 |
| 审批 | 企业现有审批系统 |
| 策略 | OPA / Casbin（权限）+ 规则表（差标） |

## 15. 实施阶段

| 阶段 | 交付物 | 验收 |
|---|---|---|
| M0 骨架 | 包结构、配置、SQLite、trace 基础设施、健康检查 | 能启动，`/health` 返回各依赖状态 |
| M1 主链路（假模型） | 网关、LangGraph 图、FakeModel、FakeTools、正常链路 | 脚本化对话可跑到"方案生成" |
| M2 工具与状态机 | 工具注册/契约/Guard、mock 库存、Checkpoint、interrupt/resume | 场景 1、5、6 通过 |
| M3 模型与知识 | 模型网关、DeepSeek 接入、制度解析、条款树/表格/引用图、混合检索、规则编译、记忆 | 真实模型下可完成查询、制度解释与引用 |
| M4 审批与差标 | 规则引擎、审批 mock、驳回、revision、幂等 | 场景 2、3、4、8 通过 |
| M5 可观测与打磨 | span 全链路、回放接口、最小 Web 页面、端到端测试 | 12 个场景全通过；可按 trace 回放 |

## 16. 验收标准

1. 一条命令启动（依赖已安装）：`uv run uvicorn itinerary_agent.main:app`；
2. 正常链路可完成：自然语言输入 → 查询 → 差标 → 审批/确认 → 下单；
3. 12 个端到端场景全部通过；
4. 中途修改预算/目的地后，旧选项、旧审批、旧确认全部失效；
5. 任意任务可按 `trace_id` 回放，并能看出每一步属于哪一层；
6. 模型调用只出现在模型网关，外部系统调用只出现在工具层（可用 import 检查或测试约束）；
7. 未审批、未确认、revision 不一致的下单请求全部被拒绝并留审计；
8. RAG 不可用时主流程继续，差标判定仍然有效；
9. 跨条款、例外、表格、版本问题能引用正确条款，而不是只给相似段落；
10. 检索不足时返回 `insufficient`，明确说明制度未覆盖，不编造；
11. 每条差标规则都能追溯到 `source_clause_id` 和 `policy_version`。

## 17. 风险与取舍

| 风险 | 影响 | 应对 |
|---|---|---|
| 制度文档外发 embedding | 合规风险 | demo 用模拟文档；生产评估私有化 embedding |
| 条款/引用解析错误 | 规则错误或回答引用错条款 | 规则 + LLM 辅助抽取 + 人工校对 + 入库校验 |
| 表格提取错误 | 差标判定错误 | 表格结构校验、来源行核对、金标测试 |
| 制度版本漂移 | 使用过期标准 | `policy_version` + 生效日期 + `supersedes` + 检索过滤 |
| 图扩展过度 | 上下文膨胀、误召回 | 限制 1–2 跳与最大条款数；RRF + 置信度门控 |
| Milvus 单点/未启动 | RAG 不可用 | 健康检查、降级、规则引擎兜底 |
| 模型输出不稳定 | 槽位/规划错误 | 结构化输出、schema 校验、修复重试、场景回归 |
| 演示范围膨胀 | 工期延长 | 按 M0–M5 分阶段，未列入范围的层只留接口 |
| HITL 并发操作 | 状态被覆盖 | 每任务同时只允许一个待处理决策；恢复时校验版本 |
| mock 与真实系统行为偏差 | 迁移成本 | 适配器接口隔离；为真实系统保留契约测试 |
| 外部 API 限流 | 入库/查询失败 | 批处理、退避、缓存、降级 |

## 18. 附录

### 18.1 配置示例

```yaml
app:
  env: local
  tenant_default: demo-company

llm:
  provider: deepseek
  base_url_env: DEEPSEEK_BASE_URL
  api_key_env: DEEPSEEK_API_KEY
  tiers:
    light:     { model_env: MODEL_LIGHT }
    standard:  { model_env: MODEL_STANDARD }
    reasoning: { model_env: MODEL_REASONING }
  fallback_enabled: true

embedding:
  provider: dashscope
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  api_key_env: DASHSCOPE_API_KEY
  model: qwen3.7-text-embedding-flash
  dimensions: 1024
  batch_size: 20

milvus:
  uri: http://127.0.0.1:19530
  token: ""
  collection: itinerary_policy_clauses_v1
  metric_type: COSINE
  index_type: HNSW

policy:
  docs_dir: config/policies/docs
  review_dir: data/policy_review
  fts_enabled: true
  retrieval:
    dense_top_k: 10
    keyword_top_k: 10
    seed_top_k: 8
    max_expanded_clauses: 20
    graph_hops: 2

storage:
  sqlite_path: ./data/itinerary.db
  trace_retention_days: 7

adapters:
  mode: mock

observability:
  exporter: sqlite
  capture_prompt: false
```

环境变量中的模型 ID 由部署者填写，代码不写死具体版本。

### 18.2 错误码

| 错误码 | 含义 | 处理 |
|---|---|---|
| `INVALID_INPUT` | 入参格式错误 | 追问或拒绝 |
| `MISSING_SLOT` | 关键槽位缺失 | 回 `understand` 追问 |
| `NO_RESULTS` | 查询无结果 | 放宽条件或提示修改 |
| `POLICY_BLOCKED` | 差标阻断 | 修改或走审批 |
| `POLICY_INSUFFICIENT` | 制度条款/表格不足 | 追问或转人工确认 |
| `POLICY_REFERENCE_UNRESOLVED` | 条款引用未解析 | 使用已审核规则并标记降级 |
| `APPROVAL_REQUIRED` | 需要审批 | 进入审批流程 |
| `APPROVAL_REJECTED` | 审批驳回 | 回 `WAITING_HUMAN` |
| `STALE_REVISION` | revision 不一致 | 重新校验/审批 |
| `CONFIRMATION_REQUIRED` | 未确认 | 进入确认节点 |
| `GUARD_DENIED` | 动作准入拒绝 | 记录审计并提示 |
| `IDEMPOTENT_REPLAY` | 幂等键已处理 | 返回既有结果 |
| `TOOL_UNAVAILABLE` | 工具临时不可用 | 重试或提示稍后 |
| `MODEL_UNAVAILABLE` | 模型不可用 | 重试/降级或失败 |
| `RAG_DEGRADED` | 检索降级 | 继续主流程并提示 |

### 18.3 术语

- **Checkpoint**：LangGraph 在节点边界保存的任务状态快照；
- **人在回路（HITL）**：任务暂停等待用户确认、补充或修改；
- **revision**：任务约束的修订号，用于使下游结果失效；
- **差标**：企业差旅标准，包含机票、酒店等费用与舱位限制；
- **Guard**：动作准入判断，决定某一步能否执行；
- **Trace**：一次请求的完整调用链，由多个 Span 组成。
