本 AI Agent 整体落地做了七层分层架构，整套编排内核是基于 LangGraph 实现的。

**第一层是接入网关层**，作为整个系统统一出入口。主要负责请求接入、用户鉴权，同时会做入参、出参的敏感数据过滤，完成请求的初步校验，再把请求向下透传给 Agent 编排内核。

**第二层是 Agent 编排内核层**，这是整个系统的核心，依托 LangGraph 的 Graph 和 Checkpoint 机制管理全量任务状态。这里维护出差任务完整状态机，包含计划中、执行中、暂停、终止、取消，还有人在回路的状态切换。Checkpoint 会持久化会话上下文、子任务执行状态，当用户中途修改目的地、预算，或者触发人在回路等待用户确认的时候，就依靠 Checkpoint 保存现场，后续恢复继续执行，不用全流程重跑。会话管理、任务拆解、子任务局部更新这些核心逻辑，都落在这一层。

**第三层是工具管理层**，主要承担工具的注册、发现、调用鉴权。重点处理工具调用带来的副作用，对写类操作做沙箱隔离，MCP 协议的适配封装全部在这一层完成。像机票酒店查询、差标校验、审批提交这些业务工具，都注册在这里，编排内核不会直接调用底层业务接口，全部经过这一层做风险管控。

**第四层是知识与记忆层**，承载 RAG 知识库和整套用户记忆能力。记忆做了区分：会话短期记忆、工作记忆、用户长期偏好记忆。多企业的差旅制度知识库也放在这里，给上层 Agent 提供检索能力；同时不会把完整的知识库大文本塞到编排内核状态里，编排层只拿引用 ID，真正数据由本层读取返回。

**第五层是模型网关层**，是所有大模型调用的唯一出口。内部实现多层缓存、分档路由策略，根据任务复杂度做模型调度，简单意图识别用轻量模型，复杂的任务规划、风险推理路由到大模型，屏蔽底层不同厂商模型的差异。

**第六层是控制层，也就是安全与决策控制层**。做统一的执行准入判断，对请求、工具调用、模型输出做管控。包含权限校验、操作风险拦截，判断当前 Agent 这一步动作到底能不能执行，相当于给整个 Agent 增加一道安全闸门。

**第七层是可观测与评估层**。基于 Trace 实现链路追踪，支持 TraceID 链路回放。这里有一个工程上的问题：普通 Trace 更多是横向的模块埋点，只能看到各个模块各自日志。所以我们额外建设了端到端全链路视角，做纵向的链路切割，可以看到**一次完整用户请求在七层架构之间流转、状态变更的全过程**，方便区分故障是编排逻辑、工具、知识库还是模型网关带来的问题，辅助线上定位故障。

当前agent是差旅对话助手即行程预订 Agent。员工用自然语言提差旅需
求，比如“下周二去北京出差两天，住在王府井附近，预计 1000 元 以内”，Agent 把行程咨询、
签证查询、行程规划、机票酒店查询、差标校验、审批、下单这些流程串起来。原来用户要在多
个系统之间切来切去，操作步骤很多，目标是把流程压缩到对话里完成。

假设外部有用户系统、权限系统，角色系统，公司规章制度的PDF
外部系统全部采用模拟数据来完成，比如我要获取当前用户信息，直接模拟返回数据。

## 本地运行

依赖与中间件由使用者安装。推荐用 Compose 启动 PostgreSQL、Redis、API、worker 和 Web：

```bash
cp .env.example .env          # scripted 模式可以先不填 Key
make db-up                    # PostgreSQL 55432 / Redis 56379
make migrate                  # Alembic upgrade head
make api                      # http://127.0.0.1:8000
make worker                   # http://127.0.0.1:8001
```

或者一次启动核心栈：

```bash
docker compose --profile core up -d --build
make higress-up                  # 接入本机已有的 Higress 网关
```

- Higress 统一入口：http://127.0.0.1:8081
- Web（Nginx + Vue 构建）：http://127.0.0.1:8080
- API：http://127.0.0.1:8000
- Worker：http://127.0.0.1:8001
- 就绪检查：`GET /readyz`；指标：`GET /metrics`
- Higress 控制台：http://127.0.0.1:8002

网关把 `/chat`、`/tasks`、`/traces` 等业务路径直连 API，其余路径交给
Web；详见 `docs/runbooks/higress.md`。

测试与检查：

```bash
make test                     # 需要 TEST_DATABASE_URL
make eval                     # 金标集 + 阈值，失败返回非零
make lint
make typecheck
```

默认 `MODEL_MODE=scripted`、`ADAPTER_MODE=mock`、`AUTH_MODE=mock`，不访问真实模型或外部业务系统。
切换 live 模式需要配置 DeepSeek / DashScope Key，并启动本地 Milvus（`127.0.0.1:19530`）。
生产环境禁止 mock 鉴权，必须配置 JWT 或 OIDC。

外部依赖支持两种 mock 形态：

```bash
# 进程内 mock（默认）
ADAPTER_MODE=mock

# 独立 HTTP mock 服务 + 真实 HTTP 适配器
docker compose --profile core --profile mocks up -d --build mock-deps api worker
ADAPTER_MODE=http MOCK_DEPS_URL=http://mock-deps:9003 ...
```

HTTP 模式覆盖用户、库存、审批、下单；超时/重试/trace 透传与幂等回放有契约测试。

## 生产化基线（P0）

- PostgreSQL 业务库 + Alembic 迁移 + Postgres Checkpoint
- API / worker 分离；审批通过 outbox + lease 驱动
- 任务恢复租约，避免用户和 worker 并发恢复
- JWT / OIDC 鉴权，本地 mock IdP 仅用于开发
- Redis 限流与 LLM 缓存；span/outbox/缓存/幂等键保留清理
- 模型主备切换、结构化输出校验/修复、成本账本
- API 加固：CORS/TrustedHost、scope 强制、任务/会话归属、游标分页、SSE 心跳与超时
- 工具治理：schema/超时/required_scopes/错误分类/审计覆盖
- JSON 日志、Prometheus 指标与告警、OTel 接入点
- Dockerfile、Compose core、GitHub Actions CI

设计取舍见 `docs/adr/`，运维步骤见 `docs/runbooks/`。
人工验收与观测观察方法见 `docs/runbooks/p0-acceptance.md`，
模型流式/熔断/prompt 版本见 `docs/runbooks/model-gateway.md`。

## 五件套可观测

```bash
make obs-up    # 自动读取 Langfuse key，启动 core + observability
```

- Grafana：http://127.0.0.1:13000（monitoring-stack，含 `Itinerary Agent` 看板）
- Prometheus：http://127.0.0.1:19090（含 `itinerary-agent` 告警规则）
- SkyWalking UI：http://127.0.0.1:18080（服务目录受限，见 Runbook）
- Kibana：http://127.0.0.1:5601（data stream `logs-itinerary`）
- Langfuse：http://127.0.0.1:3030

数据流：应用 OTLP → Collector → SkyWalking / Langfuse；Docker 日志 → Elasticsearch；
Prometheus 抓取 API/worker/Collector 指标；Grafana 自动加载看板。
告警规则在 `deploy/prometheus/alerts.yml`，共享 Prometheus 通过
`/etc/prometheus/rules/itinerary-alerts.yml` 加载。
详见 `docs/runbooks/observability.md`。

## 已实现

- 七层分包、应用服务/仓储分层、依赖与 SQL 边界检查
- LangGraph 编排、Postgres Checkpoint、人在回路确认/恢复
- API / worker 分离，outbox 事件驱动审批恢复，任务级 lease
- 工具注册、参数校验、mock 用户/库存/审批/下单、幂等写操作
- 差标规则编译与确定性求值、动作准入、审计
- 制度条款树/引用图/表格、pg_trgm + Milvus 混合检索、context pack
- revision 修改、审批驳回/通过、取消/暂停
- Trace/span 全链路记录与树形回放
- 模型主备切换、Redis 共享熔断、真流式、prompt 版本注册表、任务预算、结构化输出校验/修复、成本账本
- JWT/OIDC 鉴权、Redis 限流与缓存
- 结构化日志、Prometheus 指标、OTel 接入点
- 12 个端到端/集成场景
- 观测控制台 API：trace 列表/概览、流转图、Checkpoint 历史、反馈与 badcase 回流
- 审批工作台 API：审批列表/详情、任务当前状态
- JSONL 评测金标集：槽位、差标、RAG（recall@5/MRR/引用准确率/insufficient）、
  审批/revision、prompt 版本对比、badcase 回放；阈值进 CI（`make eval`）

## 前端控制台（Vue）

```bash
cd web
npm install        # 由你安装前端依赖
npm run dev        # http://127.0.0.1:5211
```

Vite 会把 `/chat`、`/tasks`、`/traces`、`/admin`、`/feedback`、`/badcases`
代理到本地后端 `127.0.0.1:8000`。Compose 中的 Web 使用 Nginx 在 `8080` 提供构建产物。

页面：

- `/`：差旅助手对话，支持确认、修改需求；审批与对话分离
- `/conversations`：全部对话记录，点击查看消息历史、任务和当前进展
- `/approvals`：审批工作台，展示待审批任务的差旅需求、超标明细和候选方案
- `/flow`：输入 `trace_id` 查看节点/边流转图、聊天记录和审批信息，每秒高亮下一次流转
- `/trace`：输入 `trace_id` 查看调用树、Checkpoint 历史、聊天对话和审批信息，并提交反馈
- `/overview`：错误率、分层延迟、模型 token/成本、按 task 聚合 trace（先选 task 再看相关 trace）和 badcase

```bash
npm run build      # 类型检查 + 生产构建
```
