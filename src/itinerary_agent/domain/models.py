from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class TaskStatus(StrEnum):
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


class RequestContext(BaseModel):
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


class TripRequest(BaseModel):
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


class UserProfile(BaseModel):
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
    rule_id: str
    category: Literal["flight", "hotel", "date", "other"]
    severity: Literal["block", "warn"]
    message: str
    limit: float | None = None
    actual: float | None = None
    source_clause_id: str | None = None


class PolicyResult(BaseModel):
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
    task_id: str
    status: TaskStatus
    revision: int
    policy_passed: bool | None = None
    requires_approval: bool = False
    approval_status: ApprovalStatus | None = None
    confirmed: bool = False


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


class UserMemory(BaseModel):
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


class Event(BaseModel):
    type: Literal["status", "progress", "token", "interrupt", "result", "error"]
    data: dict
