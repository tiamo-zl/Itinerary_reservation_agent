# 差旅预订 Agent 生产级评审记录

> **历史快照（2026-10-23）**：本评审记录的是 P0/P1/P2 之前的状态
> （SQLite、49 tests、无 Docker/CI/告警）。当前状态以
> `docs/status/2026-11-01-production-hardening-status.md` 为准。

- 日期：2026-10-23
- 对象：`Itinerary_reservation_agent`（M0–M5 已完成）
- 方式：源码逐文件阅读 + 全量测试实测（`uv run pytest -q` → 49 passed in 3.58s）
- 结论：**当前不满足"可上生产"，但作为"生产级形态 / Agent 工程标杆"的学习项目足够格。主要差距不在外部系统 mock，而在 Agent 工程本体（模型网关容错、评测体系、可观测运维、安全）。**

> 评分口径：所有分数/等级为本评审基于代码阅读与测试实测作出的评估判断（0–100 / A–C），非实测运行指标；仅用于表达相对达标程度。

## 1. 评审方法

阅读文件清单（关键证据来源）：

- `CLAUDE.md`、`readme.md`、`AGENTS.md`
- 设计：`docs/superpowers/specs/2026-10-21-itinerary-agent-design.md`
- 实现计划：`docs/superpowers/plans/2026-10-21-itinerary-agent-implementation.md`（26 Task，M0–M5）
- 代码：`infra/container.py`、`api/routes.py`、`api/context.py`、`api/pii.py`、`control/guard.py`、`control/service.py`、`observability/tracing.py`、`orchestration/service.py`、`orchestration/graph.py`、`tools/service.py`、`model_gateway/gateway.py`、`model_gateway/router.py`、`knowledge/service.py`、`knowledge/memory.py`、`adapters/*`（全部 mock）
- 测试：`tests/scenarios.py`、`tests/fakes.py` 及全量测试运行结果

## 2. Mock 边界清单（外部系统全部 mock——属范围决策，非工程缺陷）

| Mock 对象 | 所在文件 | 模拟了什么 | 真实对应物 |
|---|---|---|---|
| 用户/权限/角色系统 | `adapters/mock/users.py` | 硬编码 u001 张三（L2）、u002 李四（L3） | 企业用户中心 |
| 机票库存 | `adapters/mock/inventory.py` | 固定 2 航班：CA1501 ¥1280、MU5101 ¥980 | GDS/航司库存 |
| 酒店库存 | `adapters/mock/inventory.py` | 固定 2 家：王府井 ¥480、国贸 ¥720 | OTA/PMS 库存 |
| 审批系统 | `adapters/mock/approval.py` | SQLite 表 + 5 秒自动通过 + 手动驳回 | 企业 BPM/审批平台 |
| 下单系统 | `adapters/mock/booking.py` | 生成 booking_id + 幂等表防重放 | 航司/酒店预订系统 |
| 大模型（默认模式） | `adapters/scripted_model.py` | 预设响应队列；embedding 全 0 | DeepSeek + DashScope |
| 鉴权 | `api/context.py` | `X-Mock-User` 头映射用户/角色 | 真实鉴权中间件/SSO |
| 制度文档 | `config/policies/demo-company.yaml` + `config/policies/docs/demo-travel-policy.json` | 手写差标规则 + 模拟制度 | 企业制度 PDF → 编译管线 |
| 审批恢复机制 | `orchestration/approval_poller.py` | 每 2 秒轮询恢复 `WAITING_APPROVAL` | 审批系统回调/Webhook |

**不是 mock 的部分**：七层业务逻辑（编排、状态机、guard、差标求值、审计、条款树/引用图检索、trace）均为真实代码；SQLite 为真实存储；Milvus 为真实依赖（live 模式，尚未完成联调）。mock 通过 `adapters/interfaces.py` 的 Protocol 隔离，替换真实系统只改 `infra/container.py` 装配。

已知 mock 间不一致点：`api/context.py` 含 u003（other-company 租户）用于演示多租户，但 `MockUserDirectory` 中无 u003，流程调用 `get_user_profile` 会 KeyError。

## 3. 生产级能力评估（第一轮：全维度）

达标机制（设计机制层）：

| 维度 | 分 | 证据 |
|---|---|---|
| 分层架构与依赖单向 | 95 | `api/routes.py` 只碰 `container.orchestrator` 接口；`infra/container.py` 唯一装配点；`test_import_boundaries.py` 边界测试 |
| 状态机与断点恢复 | 90 | `service.py::apply_amendment` revision++ 并清空旧选项/审批/确认；SQLite Checkpoint + interrupt/resume 真实 |
| 确定性控制与幂等 | 85 | `guard.py::guard_action` 对 `book_*` 前置条件链齐全；审计表；fail-closed |
| 测试覆盖 | 85 | 49 测试全过，覆盖 12 场景、幂等、HITL、审批驳回、revision 失效 |
| 可观测性 | 70 | trace/span 全链路 + 树形回放；埋点写失败不影响业务 |

未达标机制（可运营能力层，与外部系统无关的部分）：

| 维度 | 分 | 证据 |
|---|---|---|
| 模型网关 live 验证 | 35 | live 装配分支存在，但 CLAUDE.md 自述未与真实 Key/Milvus 完整联调；横切能力未兑现（见 §5） |
| 安全与鉴权 | 20 | `X-Mock-User` 头可伪造任意用户/角色；PII 仅脱敏手机号+身份证（`pii.py` 两个正则） |
| 基础设施可靠性 | 15 | SQLite 单文件：无迁移（无 alembic）、无备份、无 HA；trace 7 天保留未见清理实现 |
| 外部系统真实集成 | 10 | 全部 mock，无真实契约测试（按用户口径：非关键点，不计入主要扣分） |
| 部署与运维 | 10 | 无 Dockerfile、无 CI、无指标/告警/SLO |

## 4. 重新校准：Agent 工程维度评级（剔除外部系统后）

| 维度 | 评级 | 证据 |
|---|---|---|
| 编排与状态机 | A | LangGraph + SQLite Checkpoint、interrupt/resume、revision 失效清空、幂等键，全部真实且测试覆盖 |
| 工具治理 | A | jsonschema 参数校验、风险分级、guard 前置闸门、写操作幂等 |
| 知识/记忆 | A− | 混合召回→RRF→图扩展→表格过滤→`insufficient` 防编造；但"低置信度不覆盖高置信度"未落实（`memory.py` upsert 直接覆盖） |
| 控制与安全 | B+ | fail-closed、审计留痕在；提示注入防护仅见于设计文档，代码未见专门落实 |
| 模型网关 | C | 路由/缓存有；熔断、备用模型降级、结构化输出校验+修复、成本、真流式全部未兑现 |
| 可观测性 | B | 全链路 span + 回放、写失败不影响业务；无采样、无 trace 保留清理、无外部监控集成 |
| 评测体系 | C+ | 功能测试扎实（含降级路径变体）；无 RAG 金标评测集、无 LLM-as-judge、无 prompt 版本对比 |
| 工程纪律 | A | 依赖单向、组合根唯一装配、配置外置、import 边界测试 |

## 5. 模型网关：设计承诺 vs 实际落实（最关键硬伤）

口径：按 `model_gateway/gateway.py`、`router.py` 代码核实（2026-10-23）。

| 能力 | 设计承诺（§7） | 实际落实 | 落实度 |
|---|---|---|---|
| 分档路由 | 有 | `resolve_model` 按 tier 解析 | 100% |
| 确定性缓存 | 有 | `llm_cache` 表，仅 classify/understand | 100% |
| 超时与重试 | 有 | SDK 自带 `timeout=30, max_retries=2` | 100%（依赖 SDK） |
| 备用模型降级 | 有 | 无 fallback 实现 | 0% |
| 熔断 | 有 | 无 | 0% |
| 结构化输出校验+修复 | 有 | 仅加 `json_object` 提示，无 schema 校验、无失败修复重试 | 30% |
| 成本统计 | 有 | `llm_calls` 表存在，`cost_usd` 恒 0（注释自认待补价格表） | 30% |
| 真流式输出 | 有 | `stream()` 为伪流式（先 complete 再一次性 yield，注释自认） | 0% |

## 6. 上生产的硬伤清单与升级路径

硬伤（均与外部系统无关，属 Agent 工程本体）：

1. **模型网关容错未兑现**：真实模型必有 429/超时/输出不合规，当前无熔断、无备用模型降级、无 schema 校验修复、stream 伪流式。模型一抖动整个 agent 无兜底。
2. **评测体系缺失**：上线前无法回答"RAG 答得对不对、模型输出稳不稳、prompt 改没改坏"。设计 8.8 承诺的六类金标问题（跨条款/例外/表格/版本/多跳/无答案）未落地。
3. **可观测与运维未闭环**：有 trace 无采样/清理/告警，无法支撑线上故障定位。
4. **安全红线**：鉴权可伪造（`X-Mock-User`）；提示注入防护未落实；PII 脱敏覆盖不足。

升级优先级：**① 模型网关容错（熔断/降级/结构化校验/真流式）→ ② 评测体系（RAG 金标集 + 场景回归 + prompt 版本对比）→ ③ 可观测运维（采样/保留清理/告警）→ ④ 鉴权与注入防护**。

## 7. 最终判断

- 作为**学习/示范意义的标杆 Agent 项目**：够格。核心决策（状态最小化、确定性控制、双唯一出口、防编造、全链路可观测）均做对且落地扎实，是高质量的架构蓝本。
- 作为**可上生产的 Agent**：当前不行。差距不在代码风格或外部系统 mock，而在 Agent 工程本体的容错、评测、运维、安全四块空白。
