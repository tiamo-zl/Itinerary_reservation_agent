"""共享领域模型。

这些模型是七层之间的契约：api、orchestration、tools、knowledge、
model_gateway、control 都只依赖这里，不互相依赖具体实现。

注意：LangGraph 状态里存的是这些模型的 dict 形式（model_dump），
因为 Checkpoint 需要 JSON 可序列化；节点边界再用 model_validate 转回来。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


# ===== 任务状态与模型档位 =====
class TaskStatus(StrEnum):
    """任务状态机。终态为 COMPLETED / CANCELLED / FAILED。"""

    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    WAITING_HUMAN = "WAITING_HUMAN"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ModelTier(StrEnum):
    LIGHT = "light"
    STANDARD = "standard"
    REASONING = "reasoning"


class HumanRequestType(StrEnum):
    CLARIFY = "clarify"
    CONFIRM_OPTION = "confirm_option"
    OVER_POLICY = "over_policy"
    APPROVAL_REJECTED = "approval_rejected"


# ===== 请求与模型调用上下文 =====
class RequestContext(BaseModel):
    """一次用户请求的上下文，由网关创建，沿七层向下传递。

    trace_id 用于全链路回放；tenant_id/user_id 用于数据隔离与审计。
    """

    trace_id: str
    tenant_id: str
    user_id: str
    roles: list[str] = Field(default_factory=list)
    session_id: str
    locale: str = "zh-CN"


class CallContext(BaseModel):
    trace_id: str
    tenant_id: str
    task_id: str | None = None
    purpose: Literal["understand", "plan", "explain", "summarize", "classify", "embed"]
    prompt_version: str = "v1"


# ===== 差旅需求与候选方案 =====
class TripRequest(BaseModel):
    """从自然语言中抽取出的结构化差旅需求。

    字段允许为空，由 understand 节点负责追问；不要在这里做业务校验。
    """

    destination_city: str | None = None
    origin_city: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    budget_limit: float | None = None
    hotel_area: str | None = None
    cabin: str | None = None
    need_flight: bool = True
    need_hotel: bool = True
    purpose: str | None = None


# ===== 用户与差旅标准 =====
class UserProfile(BaseModel):
    """用户职级/部门信息，来自外部用户系统的适配器（demo 为 mock）。"""

    user_id: str
    tenant_id: str
    name: str
    employee_level: str
    department: str
    city: str
    roles: list[str] = Field(default_factory=list)
    frequent_traveler_no: str | None = None


class FlightOption(BaseModel):
    option_id: str
    airline: str
    flight_no: str
    origin: str
    destination: str
    depart_at: str
    arrive_at: str
    cabin: str
    price: float
    refundable: bool
    seats_left: int


class HotelOption(BaseModel):
    option_id: str
    hotel_name: str
    city: str
    area: str
    room_type: str
    price_per_night: float
    refundable: bool
    distance_to_center_km: float


class SearchResults(BaseModel):
    flights: list[FlightOption] = Field(default_factory=list)
    hotels: list[HotelOption] = Field(default_factory=list)


class SelectedOptions(BaseModel):
    flight_id: str | None = None
    hotel_id: str | None = None


class Violation(BaseModel):
    """单条差标违规。source_clause_id 用于回引制度条款。"""

    rule_id: str
    category: Literal["flight", "hotel", "date", "other"]
    severity: Literal["block", "warn"]
    message: str
    limit: float | None = None
    actual: float | None = None
    source_clause_id: str | None = None


class PolicyResult(BaseModel):
    """差标判定结果。

    - passed=False 且 requires_approval=False：不可继续；
    - passed=False 且 requires_approval=True：允许走审批；
    - passed=True：可直接进入确认/下单。
    """

    passed: bool
    requires_approval: bool
    violations: list[Violation] = Field(default_factory=list)
    policy_version: str


class ApprovalRef(BaseModel):
    approval_id: str
    status: ApprovalStatus
    submitted_at: datetime | None = None
    comment: str | None = None


class HumanRequest(BaseModel):
    type: HumanRequestType
    message: str
    options: list[dict] = Field(default_factory=list)


class Decision(BaseModel):
    action: Literal["approve", "reject", "modify", "select", "pause", "cancel", "continue"]
    selected: SelectedOptions | None = None
    amended_request: TripRequest | None = None
    comment: str | None = None
    approval_status: ApprovalStatus | None = None


class GuardResult(BaseModel):
    allowed: bool
    code: str
    message: str
    required_action: str | None = None


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ToolResult(BaseModel):
    ok: bool
    data: dict | None = None
    error: ToolError | None = None
    trace_id: str = ""


class ToolSpec(BaseModel):
    name: str
    description: str
    side_effect: Literal["read", "write"]
    risk: Literal["low", "medium", "high"]
    required_scopes: list[str] = Field(default_factory=list)
    idempotent: bool = True
    timeout_ms: int = 5000
    input_schema: dict
    output_schema: dict


class TaskSnapshot(BaseModel):
    """控制层需要的窄化任务视图。

    guard 不应该依赖完整的 TravelTaskState，否则控制层会反向依赖编排层。
    """

    task_id: str
    status: TaskStatus
    revision: int
    policy_passed: bool | None = None
    requires_approval: bool = False
    approval_status: ApprovalStatus | None = None
    confirmed: bool = False


# ===== 制度知识：条款树、表格与检索上下文 =====
class PolicyFilters(BaseModel):
    """检索时用于过滤表格行/条款的元数据；不是权限条件。"""

    city_tier: int | None = None
    employee_level: str | None = None
    effective_date: str | None = None


class PolicyClause(BaseModel):
    """条款树中的一个节点；refs 是已解析的引用条款 ID。"""

    clause_id: str
    path: str
    title: str
    text: str
    clause_type: str
    policy_version: str
    table_id: str | None = None
    refs: list[str] = Field(default_factory=list)


class PolicyTable(BaseModel):
    """结构化表格：rows 保留列名，检索时按职级/城市过滤，不做文本切分。"""

    table_id: str
    source_clause_id: str
    columns: list[str]
    rows: list[dict]


class PolicyContext(BaseModel):
    """一次制度检索的结果包。

    degraded：依赖不可用（如 Milvus/embedding 超时），主流程继续；
    insufficient：关键条款/表格缺失，回答必须明确"制度未覆盖"。
    """

    clauses: list[PolicyClause]
    tables: list[PolicyTable]
    citations: list[str]
    policy_version: str
    degraded: bool = False
    insufficient: bool = False
    trace: dict = Field(default_factory=dict)


class UserMemory(BaseModel):
    """跨会话的用户偏好；低置信度不覆盖高置信度，且不写敏感信息。"""

    memory_id: str
    tenant_id: str
    user_id: str
    kind: Literal["preference", "habit", "constraint"]
    key: str
    value: str
    confidence: float = 0.8
    source_task_id: str | None = None
    updated_at: datetime
    expires_at: datetime | None = None


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Completion(BaseModel):
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    provider: str | None = None
    fallback_from: str | None = None


class Event(BaseModel):
    """网关 SSE 事件的统一结构。

    interrupt 事件会携带 human_request，前端据此展示确认/修改表单。
    """

    type: Literal["status", "progress", "token", "interrupt", "result", "error"]
    data: dict
