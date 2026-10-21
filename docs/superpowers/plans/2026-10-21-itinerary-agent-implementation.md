# 差旅预订 Agent 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/superpowers/specs/2026-10-21-itinerary-agent-design.md` 实现一个可本地运行、可演示七层架构的差旅预订 Agent。

**Architecture:** 模块化单体。七层作为 Python 包隔离，依赖单向；LangGraph 负责编排与 Checkpoint，SQLite 负责状态/记忆/trace，Milvus 存制度向量，模型统一经模型网关访问。

**Tech Stack:** Python 3.13、uv、FastAPI、LangGraph、SQLite（aiosqlite）、Milvus（pymilvus）、DeepSeek（OpenAI 兼容）、DashScope `qwen3.7-text-embedding-flash`、pytest。

---

## 文件结构

```text
src/itinerary_agent/
├── __init__.py
├── main.py
├── domain/
│   ├── __init__.py
│   └── models.py              # 全部共享 Pydantic 模型与枚举
├── api/
│   ├── __init__.py
│   ├── app.py                 # create_app(container)
│   ├── context.py             # RequestContext、mock 鉴权
│   ├── pii.py                 # 脱敏
│   ├── sse.py                 # SSE 格式化
│   └── routes.py              # /chat、/tasks、/traces、/admin
├── orchestration/
│   ├── __init__.py
│   ├── events.py              # Event
│   ├── state.py               # TravelTaskState、initial_state
│   ├── graph.py               # build_graph
│   ├── service.py             # OrchestrationService
│   ├── approval_poller.py     # 审批轮询
│   └── nodes/
│       ├── __init__.py
│       ├── understand.py
│       ├── plan.py
│       ├── search.py
│       ├── policy.py
│       ├── approval.py
│       ├── confirm.py
│       ├── book.py
│       └── respond.py
├── tools/
│   ├── __init__.py
│   ├── contracts.py           # ToolSpec / ToolResult
│   ├── registry.py            # ToolRegistry
│   ├── service.py             # ToolService
│   └── builtin.py             # 内置工具处理器
├── knowledge/
│   ├── __init__.py
│   ├── chunker.py             # PDF 解析与切分
│   ├── embedder.py            # EmbeddingPort 实现
│   ├── milvus_store.py
│   ├── service.py             # KnowledgeService
│   ├── memory.py              # 短期/长期记忆
│   └── ingest.py              # 入库 CLI
├── model_gateway/
│   ├── __init__.py
│   ├── gateway.py             # OpenAIChatGateway
│   ├── router.py              # tier → model
│   ├── cache.py               # LLM 缓存
│   └── embeddings.py          # DashScope 批量 embedding
├── control/
│   ├── __init__.py
│   ├── rules.py               # 规则模型与加载
│   ├── policy.py              # check_policy
│   ├── guard.py               # action guard
│   └── audit.py               # 审计日志
├── observability/
│   ├── __init__.py
│   ├── tracing.py             # TraceRecorder
│   └── query.py               # trace 查询与树形视图
├── adapters/
│   ├── __init__.py
│   ├── interfaces.py
│   └── mock/
│       ├── __init__.py
│       ├── users.py
│       ├── inventory.py
│       ├── approval.py
│       └── booking.py
└── infra/
    ├── __init__.py
    ├── config.py
    ├── db.py
    └── container.py

config/policies/demo-company.yaml
tests/
├── conftest.py
├── fakes.py
├── test_config.py
├── test_db.py
├── test_tracing.py
├── test_api_health.py
├── test_state.py
├── test_graph_happy_path.py
├── test_tools.py
├── test_checkpoint.py
├── test_hitl.py
├── test_policy.py
├── test_guard.py
├── test_approval.py
├── test_booking_idempotency.py
├── test_amendment.py
├── test_knowledge.py
├── test_trace_view.py
├── test_import_boundaries.py
└── test_scenarios.py
```

## 通用约定

- 所有 I/O 都是 `async`；SQLite 使用 `aiosqlite`。
- LangGraph 状态只保存 JSON 可序列化的 dict/list/str/int/bool；节点边界用 `Model.model_validate()` 转成 Pydantic。
- 时间统一使用 `datetime.now(timezone.utc)` 并转 ISO 字符串入库。
- 测试命令统一：`uv run pytest tests/<file>.py -v`。
- 每个任务结束提交一次；提交信息使用 `feat:` / `test:` / `fix:` 前缀。
- 不真实调用外部 API 的测试使用 `tests/fakes.py` 中的 Fake；真实调用测试标记 `@pytest.mark.live`。

---

## M0：骨架与基础设施

### Task 1：项目依赖与配置

**Files:**
- Modify: `pyproject.toml`
- Create: `src/itinerary_agent/__init__.py`
- Create: `src/itinerary_agent/infra/__init__.py`
- Create: `src/itinerary_agent/infra/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
from pathlib import Path
from itinerary_agent.infra.config import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = Settings(_env_file=None)
    assert s.env == "local"
    assert s.sqlite_path == Path("./data/itinerary.db")
    assert s.embedding_dimensions == 1024
    assert s.adapter_mode == "mock"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: itinerary_agent.infra.config`

- [ ] **Step 3: 写最小实现**

`pyproject.toml`：

```toml
[project]
name = "itinerary-reservation-agent"
version = "0.1.0"
description = "Production-like corporate travel reservation agent demo"
requires-python = ">=3.13"
dependencies = [
  "aiosqlite>=0.20",
  "fastapi>=0.115",
  "jsonschema>=4.23",
  "langgraph>=0.2",
  "langgraph-checkpoint-sqlite>=2.0",
  "openai>=1.40",
  "pydantic>=2.8",
  "pydantic-settings>=2.4",
  "pymilvus>=2.4",
  "pymupdf>=1.24",
  "pyyaml>=6.0",
  "sse-starlette>=2.1",
  "uvicorn[standard]>=0.30",
]

[dependency-groups]
dev = [
  "httpx>=0.27",
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "ruff>=0.6",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py313"
```

`src/itinerary_agent/infra/config.py`：

```python
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    sqlite_path: Path = Path("./data/itinerary.db")

    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    model_light: str = "deepseek-chat"
    model_standard: str = "deepseek-chat"
    model_reasoning: str = "deepseek-reasoner"

    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_api_key: str | None = None
    embedding_model: str = "qwen3.7-text-embedding-flash"
    embedding_dimensions: int = 1024
    embedding_batch_size: int = 20

    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: str = ""
    milvus_collection: str = "itinerary_policy_chunks_v1"

    adapter_mode: Literal["mock", "real"] = "mock"
    model_mode: Literal["scripted", "live"] = "scripted"
    trace_retention_days: int = 7
    capture_prompt: bool = False
    mock_approval_delay_seconds: float = 5.0
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml src/itinerary_agent tests/test_config.py
git commit -m "feat: add project settings"
```

---

### Task 2：共享领域模型

**Files:**
- Create: `src/itinerary_agent/domain/__init__.py`
- Create: `src/itinerary_agent/domain/models.py`
- Test: `tests/test_state.py`（先只测模型构造）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_state.py
from itinerary_agent.domain.models import GuardResult, PolicyResult, TaskStatus, TripRequest


def test_trip_request_defaults():
    r = TripRequest(destination_city="北京", start_date="2026-11-03", end_date="2026-11-05")
    assert r.need_flight is True
    assert r.need_hotel is True


def test_policy_result_and_guard():
    p = PolicyResult(passed=False, requires_approval=True, policy_version="2026.1")
    assert p.violations == []
    g = GuardResult(allowed=False, code="APPROVAL_REQUIRED", message="need approval")
    assert g.allowed is False
    assert TaskStatus.PLANNING.value == "PLANNING"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_state.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`src/itinerary_agent/domain/models.py`：

```python
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


class PolicySnippet(BaseModel):
    ref: str
    text: str
    section: str | None = None
    page: int | None = None
    policy_version: str


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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_state.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/domain tests/test_state.py
git commit -m "feat: add shared domain models"
```

---

### Task 3：SQLite 与建表

**Files:**
- Create: `src/itinerary_agent/infra/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_db.py
from itinerary_agent.infra.db import Database


async def test_init_and_insert_task(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    await db.execute(
        "INSERT INTO tasks (task_id, tenant_id, user_id, status, revision, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("t1", "demo-company", "u001", "PLANNING", 0, "2026-10-21T00:00:00+00:00"),
    )
    row = await db.fetchone("SELECT status FROM tasks WHERE task_id = ?", ("t1",))
    assert row["status"] == "PLANNING"
    await db.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`src/itinerary_agent/infra/db.py`：

```python
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  status TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  task_id TEXT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_memories (
  memory_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence REAL NOT NULL,
  source_task_id TEXT,
  updated_at TEXT NOT NULL,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  decision_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  inputs_hash TEXT NOT NULL,
  rule_ids TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  parent_span_id TEXT,
  name TEXT NOT NULL,
  layer TEXT NOT NULL,
  status TEXT NOT NULL,
  start_time TEXT NOT NULL,
  duration_ms REAL NOT NULL,
  attributes TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embedding_cache (
  cache_key TEXT PRIMARY KEY,
  vector TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
  call_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  tenant_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  duration_ms REAL NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL,
  comment TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database not connected")
        return self._conn

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/infra/db.py tests/test_db.py
git commit -m "feat: add sqlite storage schema"
```

---

### Task 4：Trace 基础设施

**Files:**
- Create: `src/itinerary_agent/observability/__init__.py`
- Create: `src/itinerary_agent/observability/tracing.py`
- Test: `tests/test_tracing.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tracing.py
from itinerary_agent.infra.db import Database
from itinerary_agent.observability.tracing import TraceRecorder


async def test_span_is_persisted(tmp_path):
    db = Database(tmp_path / "trace.db")
    await db.connect()
    recorder = TraceRecorder(db)
    trace_id = recorder.start_trace()
    async with recorder.span("gateway.http", layer="gateway", status_code=200):
        pass
    rows = await db.fetchall("SELECT name, layer, status FROM spans WHERE trace_id = ?", (trace_id,))
    assert rows[0]["name"] == "gateway.http"
    assert rows[0]["layer"] == "gateway"
    assert rows[0]["status"] == "ok"
    await db.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_tracing.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`src/itinerary_agent/observability/tracing.py`：

```python
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from itinerary_agent.infra.db import Database

logger = logging.getLogger(__name__)

_current_trace: ContextVar[str | None] = ContextVar("current_trace", default=None)
_current_span: ContextVar[str | None] = ContextVar("current_span", default=None)


class TraceRecorder:
    def __init__(self, db: Database):
        self.db = db

    def start_trace(self, trace_id: str | None = None) -> str:
        trace_id = trace_id or uuid4().hex
        _current_trace.set(trace_id)
        _current_span.set(None)
        return trace_id

    def current_trace_id(self) -> str | None:
        return _current_trace.get()

    @asynccontextmanager
    async def span(self, name: str, layer: str, **attributes):
        trace_id = _current_trace.get() or self.start_trace()
        span_id = uuid4().hex
        parent_id = _current_span.get()
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        token = _current_span.set(span_id)
        status = "ok"
        try:
            yield span_id
        except Exception as exc:
            status = "error"
            attributes["error"] = str(exc)
            raise
        finally:
            _current_span.reset(token)
            duration_ms = (perf_counter() - started) * 1000
            await self._write_span(
                span_id, trace_id, parent_id, name, layer, status,
                started_at, duration_ms, attributes,
            )

    async def _write_span(self, span_id, trace_id, parent_id, name, layer,
                          status, started_at, duration_ms, attributes) -> None:
        try:
            await self.db.execute(
                "INSERT INTO spans (span_id, trace_id, parent_span_id, name, layer, "
                "status, start_time, duration_ms, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    span_id, trace_id, parent_id, name, layer, status,
                    started_at.isoformat(),
                    duration_ms, json.dumps(attributes, ensure_ascii=False, default=str),
                ),
            )
        except Exception:
            logger.exception("failed to persist span %s", name)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_tracing.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/observability tests/test_tracing.py
git commit -m "feat: add trace recorder"
```

---

### Task 5：组合根与健康检查

**Files:**
- Create: `src/itinerary_agent/infra/container.py`
- Create: `src/itinerary_agent/api/__init__.py`
- Create: `src/itinerary_agent/api/app.py`
- Create: `src/itinerary_agent/main.py`
- Test: `tests/test_api_health.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_api_health.py
from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container


def test_health(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "app.db")
    container = build_container(settings)
    app = create_app(container)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_api_health.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`src/itinerary_agent/infra/container.py`：

```python
from dataclasses import dataclass

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.db import Database
from itinerary_agent.observability.tracing import TraceRecorder


@dataclass
class Container:
    settings: Settings
    db: Database
    traces: TraceRecorder

    async def start(self) -> None:
        await self.db.connect()

    async def stop(self) -> None:
        await self.db.close()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or Settings()
    db = Database(settings.sqlite_path)
    return Container(settings=settings, db=db, traces=TraceRecorder(db))
```

`src/itinerary_agent/api/app.py`：

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from itinerary_agent.infra.container import Container


def create_app(container: Container) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await container.start()
        yield
        await container.stop()

    app = FastAPI(title="Itinerary Reservation Agent", lifespan=lifespan)
    app.state.container = container

    @app.get("/health")
    async def health():
        return {"status": "ok", "env": container.settings.env}

    return app
```

`src/itinerary_agent/main.py`：

```python
from itinerary_agent.api.app import create_app
from itinerary_agent.infra.container import build_container

app = create_app(build_container())
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_api_health.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/infra/container.py src/itinerary_agent/api src/itinerary_agent/main.py tests/test_api_health.py
git commit -m "feat: add app container and health endpoint"
```

---

## M1：接入网关与编排主链路（脚本化模型）

### Task 6：请求上下文、脱敏与 SSE

**Files:**
- Create: `src/itinerary_agent/api/context.py`
- Create: `src/itinerary_agent/api/pii.py`
- Create: `src/itinerary_agent/api/sse.py`
- Test: `tests/test_pii.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pii.py
from itinerary_agent.api.pii import scrub, scrub_obj


def test_scrub_phone_and_id():
    text = "联系人 13812345678，身份证 110101199001011234"
    masked = scrub(text)
    assert "13812345678" not in masked
    assert "110101199001011234" not in masked
    assert "[PHONE]" in masked
    assert "[ID]" in masked
    assert scrub_obj({"phone": "13812345678"})["phone"] == "[PHONE]"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_pii.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`api/pii.py`：

```python
import re

ID_PATTERN = re.compile(r"\d{17}[\dXx]")
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")


def scrub(text: str) -> str:
    text = ID_PATTERN.sub("[ID]", text)
    return PHONE_PATTERN.sub("[PHONE]", text)


def scrub_obj(value):
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: scrub_obj(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_obj(v) for v in value]
    return value
```

`api/sse.py` 在输出前对数据脱敏：

```python
import json

from itinerary_agent.api.pii import scrub_obj
from itinerary_agent.domain.models import Event


def to_sse(event: Event) -> dict:
    return {"event": event.type,
            "data": json.dumps(scrub_obj(event.data), ensure_ascii=False)}
```

`api/context.py`：

```python
from uuid import uuid4

from fastapi import Request

from itinerary_agent.domain.models import RequestContext

MOCK_USERS = {
    "u001": {"tenant_id": "demo-company", "roles": ["employee"]},
    "u002": {"tenant_id": "demo-company", "roles": ["employee", "approver"]},
    "u003": {"tenant_id": "other-company", "roles": ["employee"]},
}


def build_context(request: Request) -> RequestContext:
    user_id = request.headers.get("X-Mock-User", "u001")
    mock = MOCK_USERS.get(user_id, MOCK_USERS["u001"])
    return RequestContext(
        trace_id=request.headers.get("X-Trace-Id") or uuid4().hex,
        tenant_id=mock["tenant_id"],
        user_id=user_id,
        roles=mock["roles"],
        session_id=request.headers.get("X-Session-Id", "default-session"),
    )
```

`api/sse.py`：

```python
import json

from itinerary_agent.domain.models import Event


def to_sse(event: Event) -> dict:
    return {"event": event.type, "data": json.dumps(event.data, ensure_ascii=False)}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_pii.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/api/context.py src/itinerary_agent/api/pii.py src/itinerary_agent/api/sse.py tests/test_pii.py
git commit -m "feat: add gateway context, pii filter and sse helper"
```

---

### Task 7：脚本化模型与编排图（understand → plan → respond）

**Files:**
- Create: `src/itinerary_agent/orchestration/__init__.py`
- Create: `src/itinerary_agent/orchestration/events.py`
- Create: `src/itinerary_agent/orchestration/state.py`
- Create: `src/itinerary_agent/orchestration/graph.py`
- Create: `src/itinerary_agent/orchestration/service.py`
- Create: `src/itinerary_agent/orchestration/nodes/__init__.py`
- Create: `src/itinerary_agent/orchestration/nodes/understand.py`
- Create: `src/itinerary_agent/orchestration/nodes/plan.py`
- Create: `src/itinerary_agent/orchestration/nodes/respond.py`
- Create: `src/itinerary_agent/adapters/scripted_model.py`
- Test: `tests/test_graph_happy_path.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_graph_happy_path.py
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import ModelTier, RequestContext
from itinerary_agent.orchestration.service import OrchestrationService


async def test_understand_plan_and_respond():
    model = ScriptedModelGateway([
        '{"destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights","search_hotels"]}',
        '已完成行程规划。',
    ])
    service = OrchestrationService(model=model, traces=None, tools=None, knowledge=None, control=None)
    ctx = RequestContext(trace_id="t1", tenant_id="demo-company", user_id="u001",
                         session_id="s1", roles=["employee"])
    events = [e async for e in service.start_turn(ctx, "下周二去北京出差两天")]
    assert events[-1].type == "result"
    assert events[-1].data["status"] == "COMPLETED"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_graph_happy_path.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`adapters/scripted_model.py`：

```python
from collections import deque

from itinerary_agent.domain.models import CallContext, Completion, ModelTier


class ScriptedModelGateway:
    def __init__(self, responses: list[str]):
        self._responses = deque(responses)

    async def complete(self, ctx: CallContext, messages: list[dict],
                       tier: ModelTier, response_schema: dict | None = None) -> Completion:
        text = self._responses.popleft() if self._responses else "{}"
        return Completion(text=text, model="scripted")

    async def stream(self, ctx: CallContext, messages: list[dict],
                     tier: ModelTier):
        completion = await self.complete(ctx, messages, tier)
        yield completion.text

    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]
```

`orchestration/state.py`：

```python
from typing import TypedDict
from uuid import uuid4

from itinerary_agent.domain.models import RequestContext


class TravelTaskState(TypedDict, total=False):
    task_id: str
    trace_id: str
    tenant_id: str
    user_id: str
    session_id: str
    status: str
    revision: int
    request: dict
    plan: list[str]
    options: dict
    selected: dict
    confirmed: bool
    policy_result: dict | None
    policy_refs: list[str]
    approval: dict | None
    pending_human: dict | None
    pending_amendment: dict | None
    error: dict | None
    schema_version: int


def initial_state(ctx: RequestContext, message: str) -> TravelTaskState:
    return {
        "task_id": uuid4().hex,
        "trace_id": ctx.trace_id,
        "tenant_id": ctx.tenant_id,
        "user_id": ctx.user_id,
        "session_id": ctx.session_id,
        "status": "PLANNING",
        "revision": 0,
        "request": {"raw_message": message},
        "plan": [],
        "options": {"flights": [], "hotels": []},
        "selected": {},
        "confirmed": False,
        "policy_result": None,
        "policy_refs": [],
        "approval": None,
        "pending_human": None,
        "pending_amendment": None,
        "error": None,
        "schema_version": 1,
    }
```

`orchestration/nodes/understand.py`：

```python
from itinerary_agent.domain.models import CallContext, HumanRequest, HumanRequestType, TripRequest

SYSTEM = "你是差旅需求解析器。只输出 JSON，字段与 TripRequest 一致。"


async def understand(state: dict, deps) -> dict:
    ctx = CallContext(trace_id=state["trace_id"], tenant_id=state["tenant_id"],
                      task_id=state["task_id"], purpose="understand")
    async with deps.span("orchestration.node.understand", "orchestration"):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": state["request"].get("raw_message", "")},
        ]
        completion = await deps.model.complete(ctx, messages, deps.tier_light,
                                               response_schema=TripRequest.model_json_schema())
    import json
    request = TripRequest.model_validate(json.loads(completion.text))
    if not request.destination_city:
        human = HumanRequest(type=HumanRequestType.CLARIFY, message="请提供目的地。")
        return {"status": "WAITING_HUMAN", "pending_human": human.model_dump(mode="json")}
    return {"request": request.model_dump(mode="json"), "status": "EXECUTING"}
```

`orchestration/nodes/plan.py`：

```python
import json

from itinerary_agent.domain.models import CallContext

SYSTEM = "根据差旅需求生成执行步骤。只输出 {\"steps\": [\"...\"]}。"


async def plan(state: dict, deps) -> dict:
    ctx = CallContext(trace_id=state["trace_id"], tenant_id=state["tenant_id"],
                      task_id=state["task_id"], purpose="plan")
    async with deps.span("orchestration.node.plan", "orchestration"):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(state["request"], ensure_ascii=False)},
        ]
        completion = await deps.model.complete(ctx, messages, deps.tier_reasoning)
    steps = json.loads(completion.text).get("steps", [])
    return {"plan": steps, "status": "EXECUTING"}
```

`orchestration/nodes/respond.py`：

```python
from itinerary_agent.domain.models import CallContext

SYSTEM = "用一句中文总结本次差旅方案。"


async def respond(state: dict, deps) -> dict:
    ctx = CallContext(trace_id=state["trace_id"], tenant_id=state["tenant_id"],
                      task_id=state["task_id"], purpose="summarize")
    async with deps.span("orchestration.node.respond", "orchestration"):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": str(state.get("request"))},
        ]
        completion = await deps.model.complete(ctx, messages, deps.tier_standard)
    return {"status": "COMPLETED", "summary": completion.text}
```

`orchestration/graph.py`：

```python
from functools import partial

from langgraph.graph import END, START, StateGraph

from itinerary_agent.orchestration.nodes.plan import plan
from itinerary_agent.orchestration.nodes.respond import respond
from itinerary_agent.orchestration.nodes.understand import understand
from itinerary_agent.orchestration.state import TravelTaskState


def route_after_understand(state: dict) -> str:
    return "respond" if state["status"] == "WAITING_HUMAN" else "plan"


def build_graph(deps):
    graph = StateGraph(TravelTaskState)
    graph.add_node("understand", partial(understand, deps=deps))
    graph.add_node("plan", partial(plan, deps=deps))
    graph.add_node("respond", partial(respond, deps=deps))
    graph.add_edge(START, "understand")
    graph.add_conditional_edges("understand", route_after_understand,
                                {"respond": "respond", "plan": "plan"})
    graph.add_edge("plan", "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=getattr(deps, "checkpointer", None))
```

`orchestration/service.py`：

```python
from collections.abc import AsyncIterator

from itinerary_agent.domain.models import (Event, ModelTier, RequestContext,
                                           TaskSnapshot, TaskStatus, ToolError,
                                           ToolResult, UserProfile)
from itinerary_agent.orchestration.graph import build_graph
from itinerary_agent.orchestration.state import initial_state


class _NoopSpan:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class OrchestrationService:
    def __init__(self, model, traces, tools, knowledge, control,
                 checkpointer=None, db=None, rules=None, audit=None):
        from langgraph.checkpoint.memory import MemorySaver

        self.model = model
        self.traces = traces
        self.tools = tools
        self.knowledge = knowledge
        self.control = control
        self.db = db
        self.rules = rules
        self.audit = audit
        self.checkpointer = checkpointer or MemorySaver()
        self.tier_light = ModelTier.LIGHT
        self.tier_standard = ModelTier.STANDARD
        self.tier_reasoning = ModelTier.REASONING
        self.graph = build_graph(self)

    def span(self, name: str, layer: str, **attrs):
        if self.traces is None:
            return _NoopSpan()
        return self.traces.span(name, layer, **attrs)

    def ctx_of(self, state: dict) -> RequestContext:
        return RequestContext(
            trace_id=state["trace_id"], tenant_id=state["tenant_id"],
            user_id=state["user_id"], session_id=state["session_id"], roles=[],
        )

    async def _upsert_task(self, state: dict, status: str) -> None:
        if self.db is None:
            return
        from datetime import datetime, timezone

        await self.db.execute(
            "INSERT INTO tasks (task_id, tenant_id, user_id, status, revision, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(task_id) DO UPDATE SET "
            "status=excluded.status, revision=excluded.revision, updated_at=excluded.updated_at",
            (state["task_id"], state["tenant_id"], state["user_id"], status,
             state["revision"], datetime.now(timezone.utc).isoformat()),
        )

    async def _set_task_status(self, task_id: str, status: str) -> None:
        if self.db is None:
            return
        from datetime import datetime, timezone

        await self.db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (status, datetime.now(timezone.utc).isoformat(), task_id),
        )

    async def guarded_invoke(self, state: dict, action: str, name: str,
                             args: dict) -> ToolResult:
        if self.control is not None:
            result = state.get("policy_result") or {}
            approval = state.get("approval") or {}
            snapshot = TaskSnapshot(
                task_id=state["task_id"],
                status=TaskStatus(state["status"]),
                revision=state["revision"],
                policy_passed=result.get("passed"),
                requires_approval=result.get("requires_approval", False),
                approval_status=approval.get("status"),
                confirmed=state.get("confirmed", False),
            )
            guard = self.control.guard(self.ctx_of(state), action, snapshot)
            if not guard.allowed:
                return ToolResult(ok=False, trace_id=state["trace_id"],
                                  error=ToolError(code=guard.code, message=guard.message))
        return await self.tools.invoke(self.ctx_of(state), name, args)

    async def get_user_profile(self, state: dict) -> UserProfile:
        result = await self.tools.invoke(self.ctx_of(state), "get_user_profile", {})
        return UserProfile.model_validate(result.data)

    async def start_turn(self, ctx: RequestContext, message: str) -> AsyncIterator[Event]:
        state = initial_state(ctx, message)
        config = {"configurable": {"thread_id": state["task_id"]}}
        await self._upsert_task(state, "PLANNING")
        yield Event(type="status", data={"task_id": state["task_id"], "status": "PLANNING"})
        interrupted_status: str | None = None
        async for update in self.graph.astream(state, config=config, stream_mode="updates"):
            for node, value in update.items():
                if node == "__interrupt__":
                    interrupt_value = value[0].value
                    interrupted_status = ("WAITING_APPROVAL"
                                          if interrupt_value.get("kind") == "approval"
                                          else "WAITING_HUMAN")
                    await self._set_task_status(state["task_id"], interrupted_status)
                    yield Event(type="interrupt", data={"task_id": state["task_id"],
                                                        "human_request": interrupt_value})
                else:
                    yield Event(type="progress", data={"task_id": state["task_id"], "node": node})
        final = await self.graph.aget_state(config)
        final_status = interrupted_status or final.values["status"]
        if interrupted_status is None:
            await self._upsert_task(state, final_status)
        yield Event(type="result", data={"task_id": state["task_id"],
                                         "status": final_status,
                                         "summary": final.values.get("summary", "")})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_graph_happy_path.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/orchestration src/itinerary_agent/adapters/scripted_model.py tests/test_graph_happy_path.py
git commit -m "feat: add orchestration graph with scripted model"
```

---

### Task 8：/chat API 与集成测试

**Files:**
- Create: `src/itinerary_agent/api/routes.py`
- Modify: `src/itinerary_agent/api/app.py`
- Modify: `src/itinerary_agent/infra/container.py`
- Test: `tests/test_api_chat.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_api_chat.py
from fastapi.testclient import TestClient

from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.api.app import create_app
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container


def test_chat_stream(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "chat.db")
    container = build_container(settings)
    container.model = ScriptedModelGateway([
        '{"destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights"]}',
        '已生成方案。',
    ])
    container.orchestrator = container.build_orchestrator()
    app = create_app(container)
    with TestClient(app) as client:
        with client.stream("POST", "/chat", json={"message": "下周二去北京"}) as resp:
            body = "".join(resp.iter_text())
    assert resp.status_code == 200
    assert "event: result" in body
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_api_chat.py -v`
Expected: FAIL — 404 / missing routes

- [ ] **Step 3: 写实现**

`api/routes.py`：

```python
import json

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from itinerary_agent.api.context import build_context
from itinerary_agent.api.pii import scrub
from itinerary_agent.api.sse import to_sse


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default-session"


def build_router(container) -> APIRouter:
    router = APIRouter()

    @router.post("/chat")
    async def chat(payload: ChatRequest, request: Request):
        ctx = build_context(request)
        container.traces.start_trace(ctx.trace_id)

        async def events():
            async for event in container.orchestrator.start_turn(ctx, scrub(payload.message)):
                yield to_sse(event)

        return EventSourceResponse(events())

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        row = await container.db.fetchone(
            "SELECT task_id, status, revision FROM tasks WHERE task_id = ?", (task_id,)
        )
        return dict(row) if row else {"error": "not found"}

    return router
```

`api/app.py` 增加：

```python
from itinerary_agent.api.routes import build_router

# 在 create_app 内、return app 前：
app.include_router(build_router(container))
```

`infra/container.py` 增加构造方法：

```python
from itinerary_agent.orchestration.service import OrchestrationService

# Container 内：
model: object | None = None
orchestrator: object | None = None
tools: object | None = None
knowledge: object | None = None
control: object | None = None

def build_orchestrator(self) -> OrchestrationService:
    return OrchestrationService(
        model=self.model or self._default_model(),
        traces=self.traces,
        tools=self.tools,
        knowledge=self.knowledge,
        control=self.control,
        checkpointer=self.checkpointer,
        db=self.db,
        rules=self.rules,
        audit=self.audit,
    )

def _default_model(self):
    from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
    return ScriptedModelGateway([])
```

`start()` 中在 `db.connect()` 之后：

```python
if self.orchestrator is None:
    self.orchestrator = self.build_orchestrator()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_api_chat.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/api src/itinerary_agent/infra/container.py tests/test_api_chat.py
git commit -m "feat: expose chat endpoint"
```

---

## M2：工具契约、状态机与 Checkpoint

### Task 9：工具契约与注册表

**Files:**
- Create: `src/itinerary_agent/tools/__init__.py`
- Create: `src/itinerary_agent/tools/contracts.py`
- Create: `src/itinerary_agent/tools/registry.py`
- Create: `src/itinerary_agent/tools/service.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools.py
import pytest

from itinerary_agent.domain.models import RequestContext, ToolSpec
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


async def test_tool_invoke_validates_and_returns(tmp_path):
    registry = ToolRegistry()

    async def echo(ctx, args):
        return {"echo": args["value"]}

    registry.register(
        ToolSpec(name="echo", description="echo", side_effect="read", risk="low",
                 input_schema={"type": "object", "properties": {"value": {"type": "string"}},
                               "required": ["value"]},
                 output_schema={"type": "object"}),
        echo,
    )
    service = ToolService(registry)
    ctx = RequestContext(trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s")
    result = await service.invoke(ctx, "echo", {"value": "hi"})
    assert result.ok is True
    assert result.data == {"echo": "hi"}

    with pytest.raises(Exception):
        await service.invoke(ctx, "echo", {})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`tools/registry.py`：

```python
from collections.abc import Awaitable, Callable

from itinerary_agent.domain.models import ToolSpec

ToolHandler = Callable[[object, dict], Awaitable[dict]]


class ToolRegistry:
    def __init__(self):
        self._handlers: dict[str, tuple[ToolSpec, ToolHandler]] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._handlers:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._handlers[spec.name] = (spec, handler)

    def spec(self, name: str) -> ToolSpec:
        return self._handlers[name][0]

    def handler(self, name: str) -> ToolHandler:
        return self._handlers[name][1]

    def names(self) -> list[str]:
        return sorted(self._handlers)
```

`tools/service.py`：

```python
import jsonschema

from itinerary_agent.domain.models import RequestContext, ToolError, ToolResult
from itinerary_agent.tools.registry import ToolRegistry


class ToolService:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def invoke(self, ctx: RequestContext, name: str, args: dict) -> ToolResult:
        spec = self.registry.spec(name)
        jsonschema.validate(instance=args, schema=spec.input_schema)
        try:
            data = await self.registry.handler(name)(ctx, args)
            return ToolResult(ok=True, data=data, trace_id=ctx.trace_id)
        except Exception as exc:
            return ToolResult(ok=False, trace_id=ctx.trace_id,
                              error=ToolError(code="TOOL_UNAVAILABLE", message=str(exc), retryable=True))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/tools tests/test_tools.py
git commit -m "feat: add tool registry and service"
```

---

### Task 10：Mock 库存、用户与查询工具

**Files:**
- Create: `src/itinerary_agent/adapters/__init__.py`
- Create: `src/itinerary_agent/adapters/interfaces.py`
- Create: `src/itinerary_agent/adapters/mock/__init__.py`
- Create: `src/itinerary_agent/adapters/mock/users.py`
- Create: `src/itinerary_agent/adapters/mock/inventory.py`
- Modify: `src/itinerary_agent/tools/builtin.py`
- Test: `tests/test_search_tools.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_search_tools.py
from itinerary_agent.adapters.mock.inventory import MockFlightInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.domain.models import RequestContext


async def test_mock_search_returns_options():
    flights = MockFlightInventory()
    results = await flights.search(origin="上海", destination="北京", date="2026-11-03")
    assert results
    assert results[0].destination == "北京"

    users = MockUserDirectory()
    profile = await users.get("u001")
    assert profile.employee_level == "L2"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_search_tools.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`adapters/mock/users.py`：

```python
from itinerary_agent.domain.models import UserProfile


class MockUserDirectory:
    def __init__(self):
        self._users = {
            "u001": UserProfile(user_id="u001", tenant_id="demo-company", name="张三",
                                employee_level="L2", department="销售", city="上海",
                                roles=["employee"]),
            "u002": UserProfile(user_id="u002", tenant_id="demo-company", name="李四",
                                employee_level="L3", department="财务", city="上海",
                                roles=["employee", "approver"]),
        }

    async def get(self, user_id: str) -> UserProfile:
        return self._users[user_id]
```

`adapters/mock/inventory.py`：

```python
from itinerary_agent.domain.models import FlightOption, HotelOption


class MockFlightInventory:
    async def search(self, origin: str, destination: str, date: str) -> list[FlightOption]:
        return [
            FlightOption(option_id="f1", airline="国航", flight_no="CA1501", origin=origin,
                         destination=destination, depart_at=f"{date}T08:00", arrive_at=f"{date}T10:10",
                         cabin="economy", price=1280.0, refundable=True, seats_left=9),
            FlightOption(option_id="f2", airline="东航", flight_no="MU5101", origin=origin,
                         destination=destination, depart_at=f"{date}T12:00", arrive_at=f"{date}T14:05",
                         cabin="economy", price=980.0, refundable=False, seats_left=4),
        ]


class MockHotelInventory:
    async def search(self, city: str, check_in: str, check_out: str, area: str | None) -> list[HotelOption]:
        return [
            HotelOption(option_id="h1", hotel_name="王府井酒店", city=city, area=area or "王府井",
                        room_type="大床房", price_per_night=480.0, refundable=True,
                        distance_to_center_km=1.2),
            HotelOption(option_id="h2", hotel_name="国贸大酒店", city=city, area=area or "国贸",
                        room_type="标准间", price_per_night=720.0, refundable=True,
                        distance_to_center_km=4.5),
        ]
```

`tools/builtin.py`（先实现查询与用户）：

```python
from itinerary_agent.domain.models import ToolSpec

SEARCH_FLIGHTS = ToolSpec(
    name="search_flights", description="查询航班", side_effect="read", risk="low",
    input_schema={"type": "object", "properties": {
        "origin": {"type": "string"}, "destination": {"type": "string"}, "date": {"type": "string"}},
        "required": ["origin", "destination", "date"]},
    output_schema={"type": "object"},
)
SEARCH_HOTELS = ToolSpec(
    name="search_hotels", description="查询酒店", side_effect="read", risk="low",
    input_schema={"type": "object", "properties": {
        "city": {"type": "string"}, "check_in": {"type": "string"},
        "check_out": {"type": "string"}, "area": {"type": "string"}},
        "required": ["city", "check_in", "check_out"]},
    output_schema={"type": "object"},
)
GET_USER = ToolSpec(
    name="get_user_profile", description="获取用户职级与部门", side_effect="read", risk="low",
    input_schema={"type": "object", "properties": {}}, output_schema={"type": "object"},
)


def build_builtin_registry(registry, flights, hotels, users):
    async def search_flights(ctx, args):
        options = await flights.search(args["origin"], args["destination"], args["date"])
        return {"flights": [o.model_dump(mode="json") for o in options]}

    async def search_hotels(ctx, args):
        options = await hotels.search(args["city"], args["check_in"], args["check_out"], args.get("area"))
        return {"hotels": [o.model_dump(mode="json") for o in options]}

    async def get_user_profile(ctx, args):
        profile = await users.get(ctx.user_id)
        return profile.model_dump(mode="json")

    registry.register(SEARCH_FLIGHTS, search_flights)
    registry.register(SEARCH_HOTELS, search_hotels)
    registry.register(GET_USER, get_user_profile)
    return registry
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_search_tools.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/adapters src/itinerary_agent/tools/builtin.py tests/test_search_tools.py
git commit -m "feat: add mock inventory and user adapters"
```

---

### Task 11：搜索节点与状态持久化

**Files:**
- Create: `src/itinerary_agent/orchestration/nodes/search.py`
- Modify: `src/itinerary_agent/orchestration/graph.py`
- Modify: `src/itinerary_agent/orchestration/service.py`
- Modify: `src/itinerary_agent/infra/container.py`
- Test: `tests/test_search_node.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_search_node.py
from itinerary_agent.adapters.mock.inventory import MockFlightInventory, MockHotelInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.orchestration.service import OrchestrationService
from itinerary_agent.tools.builtin import build_builtin_registry
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


async def test_search_node_fills_options():
    registry = build_builtin_registry(ToolRegistry(), MockFlightInventory(),
                                      MockHotelInventory(), MockUserDirectory())
    model = ScriptedModelGateway([
        '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights","search_hotels"]}',
        '方案已生成。',
    ])
    service = OrchestrationService(model=model, traces=None,
                                   tools=ToolService(registry), knowledge=None, control=None)
    ctx = RequestContext(trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s")
    events = [e async for e in service.start_turn(ctx, "去北京出差")]
    final = await service.graph.aget_state({"configurable": {"thread_id": events[0].data["task_id"]}})
    assert len(final.values["options"]["flights"]) == 2
    assert len(final.values["options"]["hotels"]) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_search_node.py -v`
Expected: FAIL — 状态中没有 options

- [ ] **Step 3: 写实现**

`orchestration/nodes/search.py`：

```python
from itinerary_agent.domain.models import TripRequest


async def search(state: dict, deps) -> dict:
    request = TripRequest.model_validate(state["request"])
    async with deps.span("orchestration.node.search", "orchestration"):
        flights = []
        hotels = []
        if request.need_flight and request.origin_city and request.destination_city and request.start_date:
            result = await deps.tools.invoke(
                deps.ctx_of(state), "search_flights",
                {"origin": request.origin_city, "destination": request.destination_city,
                 "date": request.start_date},
            )
            if result.ok:
                flights = result.data["flights"]
        if request.need_hotel and request.destination_city and request.start_date and request.end_date:
            result = await deps.tools.invoke(
                deps.ctx_of(state), "search_hotels",
                {"city": request.destination_city, "check_in": request.start_date,
                 "check_out": request.end_date, "area": request.hotel_area or ""},
            )
            if result.ok:
                hotels = result.data["hotels"]
    return {"options": {"flights": flights, "hotels": hotels}, "status": "EXECUTING"}
```

`service.py` 增加：

```python
from itinerary_agent.domain.models import RequestContext

def ctx_of(self, state: dict) -> RequestContext:
    return RequestContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        user_id=state["user_id"], session_id=state["session_id"], roles=[],
    )
```

`graph.py` 在 plan 与 respond 之间加入 search：

```python
from itinerary_agent.orchestration.nodes.search import search

# build_graph 内
graph.add_node("search", partial(search, deps=deps))
graph.add_edge("plan", "search")
graph.add_edge("search", "respond")
```

`service.start_turn` 结束时 upsert 任务：

```python
from datetime import datetime, timezone

# 在 final 之后
await self._upsert_task(state, final.values["status"])
```

`OrchestrationService.__init__` 增加 `db=None` 参数，容器传入 `self.db`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_search_node.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/orchestration src/itinerary_agent/infra/container.py tests/test_search_node.py
git commit -m "feat: add search node and task persistence"
```

---

### Task 12：Checkpoint、确认中断与恢复接口

**Files:**
- Create: `src/itinerary_agent/orchestration/nodes/confirm.py`
- Modify: `src/itinerary_agent/orchestration/graph.py`
- Modify: `src/itinerary_agent/orchestration/service.py`
- Modify: `src/itinerary_agent/infra/container.py`
- Modify: `src/itinerary_agent/api/routes.py`
- Test: `tests/test_hitl.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_hitl.py
from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.domain.models import Decision, RequestContext
from itinerary_agent.orchestration.service import OrchestrationService


async def test_interrupt_and_resume():
    from tests.fakes import ScriptedDeps

    deps = ScriptedDeps(checkpointer=MemorySaver())
    service = deps.build_service()
    ctx = RequestContext(trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s")
    events = [e async for e in service.start_turn(ctx, "去北京")]
    interrupt = next(e for e in events if e.type == "interrupt")
    task_id = interrupt.data["task_id"]
    resumed = [e async for e in service.resume(ctx, task_id, Decision(action="select"))]
    assert resumed[-1].data["status"] == "COMPLETED"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_hitl.py -v`
Expected: FAIL — 没有中断

- [ ] **Step 3: 写实现**

`orchestration/nodes/confirm.py`：

```python
from langgraph.types import interrupt

from itinerary_agent.domain.models import HumanRequest, HumanRequestType


async def confirm(state: dict, deps) -> dict:
    if state.get("confirmed"):
        return {"status": "EXECUTING"}
    message = "请确认方案后继续下单。"
    policy = state.get("policy_result") or {}
    if policy.get("passed") is False:
        message = "方案不符合差标，请修改预算/选项，或取消本次任务。"
    decision = interrupt(
        HumanRequest(
            type=HumanRequestType.CONFIRM_OPTION,
            message=message,
            options=state.get("options", {}).get("flights", []),
        ).model_dump(mode="json")
    )
    if isinstance(decision, dict) and decision.get("action") == "cancel":
        return {"status": "CANCELLED"}
    return {"confirmed": True, "status": "EXECUTING"}
```

`graph.py` 增加 confirm：

```python
from itinerary_agent.orchestration.nodes.confirm import confirm

graph.add_node("confirm", partial(confirm, deps=deps))
graph.add_edge("search", "confirm")
graph.add_edge("confirm", "respond")
```

`service.py` 增加 `resume`：

```python
from langgraph.types import Command

async def resume(self, ctx: RequestContext, task_id: str, decision) -> AsyncIterator[Event]:
    config = {"configurable": {"thread_id": task_id}}
    payload = decision.model_dump()
    if decision.approval_status is not None:
        payload = {"status": decision.approval_status.value,
                   "comment": decision.comment or ""}
    yield Event(type="status", data={"task_id": task_id, "status": "EXECUTING"})
    interrupted_status: str | None = None
    async for update in self.graph.astream(Command(resume=payload), config=config,
                                           stream_mode="updates"):
        for node, value in update.items():
            if node == "__interrupt__":
                interrupt_value = value[0].value
                interrupted_status = ("WAITING_APPROVAL"
                                      if interrupt_value.get("kind") == "approval"
                                      else "WAITING_HUMAN")
                await self._set_task_status(task_id, interrupted_status)
                yield Event(type="interrupt", data={"task_id": task_id,
                                                    "human_request": interrupt_value})
            else:
                yield Event(type="progress", data={"task_id": task_id, "node": node})
    final = await self.graph.aget_state(config)
    final_status = interrupted_status or final.values["status"]
    if interrupted_status is None:
        await self._upsert_task(final.values, final_status)
    yield Event(type="result", data={"task_id": task_id, "status": final_status})
```

`container.py` 创建 Checkpointer：

```python
from langgraph.checkpoint.memory import MemorySaver

# Container 字段：checkpointer
self.checkpointer = MemorySaver()  # M2 先用内存；Task 13 换 AsyncSqliteSaver
```

`build_orchestrator` 传入 `checkpointer=self.checkpointer`；`OrchestrationService` 构造时 `graph.compile(checkpointer=...)`。

`api/routes.py` 增加 `/tasks/{task_id}/resume`：

```python
from itinerary_agent.domain.models import Decision

@router.post("/tasks/{task_id}/resume")
async def resume(task_id: str, decision: Decision, request: Request):
    ctx = build_context(request)
    container.traces.start_trace(ctx.trace_id)

    async def events():
        async for event in container.orchestrator.resume(ctx, task_id, decision):
            yield to_sse(event)

    return EventSourceResponse(events())
```

`tests/fakes.py` 先提供最小依赖：

```python
from langgraph.checkpoint.memory import MemorySaver

from itinerary_agent.adapters.mock.inventory import MockFlightInventory, MockHotelInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.orchestration.service import OrchestrationService
from itinerary_agent.tools.builtin import build_builtin_registry
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


class ScriptedDeps:
    def __init__(self, checkpointer):
        self.checkpointer = checkpointer
        self.model = ScriptedModelGateway([
            '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
            '{"steps":["search_flights","search_hotels"]}',
            '方案已生成。',
            '已确认。',
        ])
        registry = build_builtin_registry(ToolRegistry(), MockFlightInventory(),
                                          MockHotelInventory(), MockUserDirectory())
        self.tools = ToolService(registry)
        self.traces = None
        self.knowledge = None
        self.control = None

    def build_service(self):
        return OrchestrationService(
            model=self.model, traces=self.traces, tools=self.tools,
            knowledge=self.knowledge, control=self.control,
            checkpointer=self.checkpointer,
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_hitl.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/orchestration src/itinerary_agent/api/routes.py src/itinerary_agent/infra/container.py tests/test_hitl.py tests/fakes.py
git commit -m "feat: add human-in-the-loop interrupt and resume"
```

---

### Task 13：SQLite Checkpoint 与暂停/取消

**Files:**
- Modify: `src/itinerary_agent/infra/container.py`
- Modify: `src/itinerary_agent/orchestration/service.py`
- Modify: `src/itinerary_agent/api/routes.py`
- Test: `tests/test_checkpoint.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_checkpoint.py
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container


async def test_checkpoint_survives_container_restart(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "ckpt.db")
    c1 = build_container(settings)
    c1.model = ScriptedModelGateway([
        '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights","search_hotels"]}',
        '方案已生成。',
    ])
    await c1.start()
    ctx = RequestContext(trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s")
    events = [e async for e in c1.orchestrator.start_turn(ctx, "去北京出差")]
    task_id = events[0].data["task_id"]
    await c1.stop()

    c2 = build_container(settings)
    await c2.start()
    state = await c2.orchestrator.graph.aget_state(
        {"configurable": {"thread_id": task_id}}
    )
    assert state.values["options"]["flights"]
    assert state.next
    await c2.stop()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_checkpoint.py -v`
Expected: FAIL — `AsyncSqliteSaver` 尚未接入

- [ ] **Step 3: 写实现**

`container.py`：

```python
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Container 字段
conn: aiosqlite.Connection | None = None
checkpointer: AsyncSqliteSaver | None = None

async def start(self):
    await self.db.connect()
    self.conn = await aiosqlite.connect(self.settings.sqlite_path)
    self.checkpointer = AsyncSqliteSaver(self.conn)
    self.orchestrator = self.build_orchestrator()

async def stop(self):
    await self.db.close()
    if self.conn is not None:
        await self.conn.close()
```

`OrchestrationService` 构造参数 `checkpointer`；`build_graph(self)` 使用 `self.checkpointer`。

`service.resume` 增加暂停/取消：

```python
if decision.action == "cancel":
    final = await self.graph.aget_state(config)
    await self.db.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                          ("CANCELLED", datetime.now(timezone.utc).isoformat(), task_id))
    yield Event(type="result", data={"task_id": task_id, "status": "CANCELLED"})
    return
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_checkpoint.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/infra/container.py src/itinerary_agent/orchestration/service.py src/itinerary_agent/api/routes.py tests/test_checkpoint.py
git commit -m "feat: persist checkpoints in sqlite"
```

---

## M3：模型网关、知识与记忆

### Task 14：OpenAI 兼容聊天网关与分档路由

**Files:**
- Create: `src/itinerary_agent/model_gateway/__init__.py`
- Create: `src/itinerary_agent/model_gateway/router.py`
- Create: `src/itinerary_agent/model_gateway/gateway.py`
- Test: `tests/test_model_gateway.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_model_gateway.py
from itinerary_agent.model_gateway.router import resolve_model
from itinerary_agent.infra.config import Settings


def test_tier_routing():
    s = Settings(_env_file=None, model_light="light-m", model_standard="std-m", model_reasoning="reason-m")
    assert resolve_model(s, "light") == "light-m"
    assert resolve_model(s, "reasoning") == "reason-m"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_model_gateway.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`router.py`：

```python
from itinerary_agent.infra.config import Settings


def resolve_model(settings: Settings, tier: str) -> str:
    return {
        "light": settings.model_light,
        "standard": settings.model_standard,
        "reasoning": settings.model_reasoning,
    }[tier]
```

`gateway.py`：

```python
import json

from openai import AsyncOpenAI

from itinerary_agent.domain.models import CallContext, Completion, ModelTier
from itinerary_agent.infra.config import Settings
from itinerary_agent.model_gateway.router import resolve_model


class OpenAIChatGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(base_url=settings.deepseek_base_url,
                                  api_key=settings.deepseek_api_key or "missing")

    async def complete(self, ctx: CallContext, messages: list[dict],
                       tier: ModelTier, response_schema: dict | None = None) -> Completion:
        model = resolve_model(self.settings, tier.value)
        kwargs = {"model": model, "messages": messages, "temperature": 0}
        if response_schema:
            messages = messages + [{"role": "user",
                                    "content": "只输出 JSON，并满足给定 schema。"}]
            kwargs["messages"] = messages
            kwargs["response_format"] = {"type": "json_object"}
        resp = await self.client.chat.completions.create(**kwargs)
        usage = resp.usage
        return Completion(
            text=resp.choices[0].message.content or "",
            model=model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )

    async def stream(self, ctx: CallContext, messages: list[dict], tier: ModelTier):
        completion = await self.complete(ctx, messages, tier)
        yield completion.text

    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError("use DashScopeEmbedder")
```

在 `OpenAIChatGateway.__init__` 增加 `db: Database | None = None`，并在 `complete()` 中加入缓存与成本记录：

```python
import hashlib

cacheable = ctx.purpose in {"classify", "understand"}
cache_key = hashlib.sha256(
    json.dumps([model, messages], sort_keys=True, ensure_ascii=False).encode()
).hexdigest()
if cacheable and self.db is not None:
    row = await self.db.fetchone("SELECT value FROM llm_cache WHERE cache_key = ?", (cache_key,))
    if row:
        return Completion.model_validate_json(row["value"])

# 在 resp = await self.client.chat.completions.create(**kwargs) 之后：
result = Completion(
    text=resp.choices[0].message.content or "",
    model=model,
    prompt_tokens=usage.prompt_tokens if usage else 0,
    completion_tokens=usage.completion_tokens if usage else 0,
)
if self.db is not None:
    if cacheable:
        await self.db.execute(
            "INSERT OR REPLACE INTO llm_cache (cache_key, value, created_at) VALUES (?, ?, ?)",
            (cache_key, result.model_dump_json(), datetime.now(timezone.utc).isoformat()),
        )
    await self.db.execute(
        "INSERT INTO llm_calls (call_id, trace_id, task_id, tenant_id, purpose, model, "
        "prompt_tokens, completion_tokens, cost_usd, duration_ms, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uuid4().hex, ctx.trace_id, ctx.task_id, ctx.tenant_id, ctx.purpose, model,
         result.prompt_tokens, result.completion_tokens, result.cost_usd, 0.0,
         datetime.now(timezone.utc).isoformat()),
    )
return result
```

`container.py` 创建网关时传入 `db=self.db`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_model_gateway.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/model_gateway tests/test_model_gateway.py
git commit -m "feat: add openai-compatible chat gateway"
```

---

### Task 15：DashScope Embedding 与 Milvus

**Files:**
- Create: `src/itinerary_agent/model_gateway/embeddings.py`
- Create: `src/itinerary_agent/knowledge/__init__.py`
- Create: `src/itinerary_agent/knowledge/milvus_store.py`
- Create: `src/itinerary_agent/knowledge/service.py`
- Test: `tests/test_knowledge.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_knowledge.py
from itinerary_agent.knowledge.service import KnowledgeService


class FakeEmbedder:
    async def embed(self, ctx, texts):
        return [[0.1] * 1024 for _ in texts]


class FakeStore:
    async def search(self, tenant_id, vector, top_k):
        return [{"id": "c1", "text": "住宿标准 500 元", "section": "住宿标准",
                 "page": 3, "policy_version": "2026.1"}]


async def test_search_policy_returns_snippet():
    service = KnowledgeService(embedder=FakeEmbedder(), store=FakeStore())
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company"})()
    result = await service.search_policy(ctx, "北京住宿标准")
    assert result[0].section == "住宿标准"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_knowledge.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`model_gateway/embeddings.py`：

```python
from openai import AsyncOpenAI

from itinerary_agent.domain.models import CallContext
from itinerary_agent.infra.config import Settings


class DashScopeEmbedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(base_url=settings.dashscope_base_url,
                                  api_key=settings.dashscope_api_key or "missing")

    async def embed(self, ctx: CallContext, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        batch_size = self.settings.embedding_batch_size
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = await self.client.embeddings.create(
                model=self.settings.embedding_model,
                input=batch,
                dimensions=self.settings.embedding_dimensions,
            )
            vectors.extend([item.embedding for item in resp.data])
        return vectors
```

`knowledge/milvus_store.py`：

```python
from pymilvus import DataType, MilvusClient

from itinerary_agent.infra.config import Settings


class MilvusPolicyStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token)

    def ensure_collection(self) -> None:
        name = self.settings.milvus_collection
        if self.client.has_collection(name):
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=64, is_partition_key=True)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=64)
        schema.add_field("policy_version", DataType.VARCHAR, max_length=32)
        schema.add_field("section", DataType.VARCHAR, max_length=256)
        schema.add_field("page", DataType.INT64)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        schema.add_field("embedding", DataType.FLOAT_VECTOR,
                         dim=self.settings.embedding_dimensions)
        schema.add_field("effective_from", DataType.VARCHAR, max_length=10)
        schema.add_field("effective_to", DataType.VARCHAR, max_length=10)
        schema.add_field("metadata", DataType.JSON)
        index = self.client.prepare_index_params()
        index.add_index(field_name="embedding", index_type="HNSW", metric_type="COSINE",
                        params={"M": 16, "efConstruction": 200})
        self.client.create_collection(name, schema=schema, index_params=index)

    async def search(self, tenant_id: str, vector: list[float], top_k: int) -> list[dict]:
        results = self.client.search(
            collection_name=self.settings.milvus_collection,
            data=[vector], anns_field="embedding", limit=top_k,
            filter=f'tenant_id == "{tenant_id}"',
            output_fields=["text", "section", "page", "policy_version"],
        )
        hits = []
        for hit in results[0]:
            entity = hit["entity"]
            hits.append({
                "id": hit["id"],
                "text": entity["text"],
                "section": entity["section"],
                "page": entity["page"],
                "policy_version": entity["policy_version"],
            })
        return hits
```

`knowledge/service.py`：

```python
from itinerary_agent.domain.models import CallContext, PolicySnippet


class KnowledgeService:
    def __init__(self, embedder, store):
        self.embedder = embedder
        self.store = store

    async def search_policy(self, ctx, query: str, top_k: int = 5) -> list[PolicySnippet]:
        try:
            call_ctx = CallContext(trace_id=ctx.trace_id, tenant_id=ctx.tenant_id, purpose="embed")
            vector = (await self.embedder.embed(call_ctx, [query]))[0]
            hits = await self.store.search(ctx.tenant_id, vector, top_k)
            return [PolicySnippet(ref=h["id"], text=h["text"], section=h["section"],
                                  page=h["page"], policy_version=h["policy_version"])
                    for h in hits]
        except Exception:
            return []
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_knowledge.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/model_gateway/embeddings.py src/itinerary_agent/knowledge tests/test_knowledge.py
git commit -m "feat: add dashscope embedding and milvus store"
```

---

### Task 16：制度入库与记忆存储

**Files:**
- Create: `src/itinerary_agent/knowledge/chunker.py`
- Create: `src/itinerary_agent/knowledge/ingest.py`
- Create: `src/itinerary_agent/knowledge/memory.py`
- Test: `tests/test_memory.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_memory.py
from datetime import datetime, timezone

from itinerary_agent.domain.models import UserMemory
from itinerary_agent.infra.db import Database
from itinerary_agent.knowledge.memory import MemoryStore


async def test_upsert_and_read_memory(tmp_path):
    db = Database(tmp_path / "m.db")
    await db.connect()
    store = MemoryStore(db)
    memory = UserMemory(memory_id="m1", tenant_id="demo-company", user_id="u001",
                        kind="preference", key="hotel_chain", value="华住",
                        confidence=0.9, updated_at=datetime.now(timezone.utc))
    await store.upsert(memory)
    result = await store.get("demo-company", "u001", ["preference"])
    assert result[0].value == "华住"
    await db.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_memory.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`knowledge/memory.py`：

```python
from datetime import datetime, timezone

from itinerary_agent.domain.models import UserMemory
from itinerary_agent.infra.db import Database


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    async def upsert(self, memory: UserMemory) -> None:
        await self.db.execute(
            "INSERT INTO user_memories (memory_id, tenant_id, user_id, kind, key, value, "
            "confidence, source_task_id, updated_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(memory_id) DO UPDATE SET value=excluded.value, "
            "confidence=excluded.confidence, updated_at=excluded.updated_at",
            (memory.memory_id, memory.tenant_id, memory.user_id, memory.kind, memory.key,
             memory.value, memory.confidence, memory.source_task_id,
             memory.updated_at.isoformat(), memory.expires_at.isoformat() if memory.expires_at else None),
        )

    async def get(self, tenant_id: str, user_id: str, kinds: list[str]) -> list[UserMemory]:
        placeholders = ",".join("?" for _ in kinds)
        rows = await self.db.fetchall(
            f"SELECT * FROM user_memories WHERE tenant_id = ? AND user_id = ? AND kind IN ({placeholders})",
            (tenant_id, user_id, *kinds),
        )
        return [UserMemory(
            memory_id=r["memory_id"], tenant_id=r["tenant_id"], user_id=r["user_id"],
            kind=r["kind"], key=r["key"], value=r["value"], confidence=r["confidence"],
            source_task_id=r["source_task_id"],
            updated_at=datetime.fromisoformat(r["updated_at"]),
            expires_at=datetime.fromisoformat(r["expires_at"]) if r["expires_at"] else None,
        ) for r in rows]

    async def append_message(self, session_id: str, task_id: str | None, role: str, content: str) -> None:
        await self.db.execute(
            "INSERT INTO messages (session_id, task_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, task_id, role, content, datetime.now(timezone.utc).isoformat()),
        )

    async def recent_messages(self, session_id: str, limit: int = 10) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
```

`knowledge/chunker.py`：

```python
from pathlib import Path

import fitz


def extract_text(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
    return chunks
```

`knowledge/ingest.py`：

```python
import hashlib
from pathlib import Path

from itinerary_agent.domain.models import CallContext
from itinerary_agent.knowledge.chunker import chunk_text, extract_text


async def ingest_pdf(tenant_id, doc_id, policy_version, path: Path,
                     embedder, store, batch_size=20) -> int:
    store.ensure_collection()
    chunks = chunk_text(extract_text(path))
    call_ctx = CallContext(trace_id="ingest", tenant_id=tenant_id, purpose="embed")
    vectors = await embedder.embed(call_ctx, chunks)
    rows = []
    for i, (text, vector) in enumerate(zip(chunks, vectors)):
        chunk_id = hashlib.sha256(f"{doc_id}:{policy_version}:{i}:{text}".encode()).hexdigest()[:32]
        rows.append({
            "id": chunk_id, "tenant_id": tenant_id, "doc_id": doc_id,
            "policy_version": policy_version, "section": "", "page": 0,
            "text": text, "embedding": vector,
            "effective_from": "", "effective_to": "", "metadata": {},
        })
    for i in range(0, len(rows), batch_size):
        store.client.insert(collection_name=store.settings.milvus_collection,
                            data=rows[i:i + batch_size])
    return len(rows)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_memory.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/knowledge tests/test_memory.py
git commit -m "feat: add policy ingestion and memory store"
```

---

### Task 17：把真实模型与知识接入编排

**Files:**
- Modify: `src/itinerary_agent/infra/container.py`
- Modify: `src/itinerary_agent/orchestration/nodes/plan.py`
- Modify: `src/itinerary_agent/orchestration/nodes/respond.py`
- Test: `tests/test_graph_with_knowledge.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_graph_with_knowledge.py
from itinerary_agent.domain.models import PolicySnippet


class FakeKnowledge:
    async def search_policy(self, ctx, query, top_k=5):
        return [PolicySnippet(ref="c1", text="住宿标准 500 元", section="住宿标准",
                              page=3, policy_version="2026.1")]


async def test_plan_includes_policy_refs():
    from tests.fakes import ScriptedDeps
    from langgraph.checkpoint.memory import MemorySaver

    deps = ScriptedDeps(checkpointer=MemorySaver())
    deps.knowledge = FakeKnowledge()
    service = deps.build_service()
    ctx = type("Ctx", (), {"trace_id": "t", "tenant_id": "demo-company", "user_id": "u001",
                           "session_id": "s", "roles": []})()
    events = [e async for e in service.start_turn(ctx, "去北京出差")]
    final = await service.graph.aget_state({"configurable": {"thread_id": events[0].data["task_id"]}})
    assert final.values["policy_refs"] == ["c1"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_graph_with_knowledge.py -v`
Expected: FAIL — `policy_refs` 为空

- [ ] **Step 3: 写实现**

`plan.py` 完整实现：

```python
import json

from itinerary_agent.domain.models import CallContext

SYSTEM = "根据差旅需求生成执行步骤。只输出 {\"steps\": [\"...\"]}。"


async def plan(state: dict, deps) -> dict:
    refs = []
    if deps.knowledge is not None:
        snippets = await deps.knowledge.search_policy(deps.ctx_of(state), "差旅住宿与机票标准")
        refs = [s.ref for s in snippets]
    ctx = CallContext(trace_id=state["trace_id"], tenant_id=state["tenant_id"],
                      task_id=state["task_id"], purpose="plan")
    async with deps.span("orchestration.node.plan", "orchestration"):
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(state["request"], ensure_ascii=False)},
        ]
        completion = await deps.model.complete(ctx, messages, deps.tier_reasoning)
    steps = json.loads(completion.text).get("steps", [])
    return {"plan": steps, "status": "EXECUTING", "policy_refs": refs}
```

`container.py` 在 `start()` 中根据 `settings.model_mode` 选择模型：

```python
if self.settings.model_mode == "live":
    from itinerary_agent.model_gateway.gateway import OpenAIChatGateway
    self.model = OpenAIChatGateway(self.settings)
else:
    from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
    self.model = ScriptedModelGateway([])
```

同时按 `model_mode` 构造知识服务；`live` 时使用 `DashScopeEmbedder` 与 `MilvusPolicyStore`，否则 `None`。

短期记忆接入：

```python
# container.start()
from itinerary_agent.knowledge.memory import MemoryStore
self.memory = MemoryStore(self.db)

# build_orchestrator 传入 memory=self.memory
# OrchestrationService.__init__ 增加 memory=None，并保存 self.memory
# understand 节点在构造 messages 时加入最近对话：
recent = []
if deps.memory is not None:
    recent = await deps.memory.recent_messages(state["session_id"], limit=6)
messages = recent + [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": state["request"].get("raw_message", "")},
]
# start_turn 开头写入用户消息：
if self.memory is not None:
    await self.memory.append_message(state["session_id"], state["task_id"], "user", message)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_graph_with_knowledge.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/infra/container.py src/itinerary_agent/orchestration/nodes/plan.py tests/test_graph_with_knowledge.py
git commit -m "feat: wire knowledge into planning"
```

---

## M4：控制层、审批与下单

### Task 18：差标规则与求值

**Files:**
- Create: `config/policies/demo-company.yaml`
- Create: `src/itinerary_agent/control/__init__.py`
- Create: `src/itinerary_agent/control/rules.py`
- Create: `src/itinerary_agent/control/policy.py`
- Test: `tests/test_policy.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_policy.py
from itinerary_agent.control.policy import check_policy
from itinerary_agent.control.rules import PolicyRules, Rule
from itinerary_agent.domain.models import HotelOption, SearchResults, TripRequest, UserProfile


def test_over_budget_hotel_requires_approval():
    rules = PolicyRules(version="2026.1", tenant_id="demo-company", defaults={},
                        rules=[Rule(id="hotel-L1", match={"employee_level": ["L1"]},
                                    category="hotel", limit=500, severity="block",
                                    allow_approval=True)])
    user = UserProfile(user_id="u", tenant_id="demo-company", name="A", employee_level="L1",
                       department="D", city="上海")
    options = SearchResults(hotels=[HotelOption(option_id="h1", hotel_name="H", city="北京",
                                                area="王府井", room_type="大床",
                                                price_per_night=800, refundable=True,
                                                distance_to_center_km=1.0)])
    result = check_policy(TripRequest(destination_city="北京"), options, user, rules)
    assert result.passed is False
    assert result.requires_approval is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_policy.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`control/rules.py`：

```python
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Rule(BaseModel):
    id: str
    match: dict = Field(default_factory=dict)
    category: str
    limit: float | None = None
    constraint: dict = Field(default_factory=dict)
    severity: str = "warn"
    allow_approval: bool = False


class PolicyRules(BaseModel):
    version: str
    tenant_id: str
    defaults: dict = Field(default_factory=dict)
    rules: list[Rule] = Field(default_factory=list)


def load_rules(path: Path) -> PolicyRules:
    return PolicyRules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
```

`control/policy.py`：

```python
from itinerary_agent.control.rules import PolicyRules
from itinerary_agent.domain.models import (PolicyResult, SearchResults, TripRequest,
                                          UserProfile, Violation)


def _matches(rule, user: UserProfile, request: TripRequest) -> bool:
    levels = rule.match.get("employee_level")
    return not levels or user.employee_level in levels


def check_policy(request: TripRequest, options: SearchResults,
                 user: UserProfile, rules: PolicyRules) -> PolicyResult:
    violations: list[Violation] = []
    requires_approval = False
    hotel_rules = [r for r in rules.rules if r.category == "hotel" and _matches(r, user, request)]
    for rule in hotel_rules:
        for hotel in options.hotels:
            if rule.limit is not None and hotel.price_per_night > rule.limit:
                violations.append(Violation(
                    rule_id=rule.id, category="hotel", severity=rule.severity,
                    message=f"{hotel.hotel_name} 每晚 {hotel.price_per_night} 超过标准 {rule.limit}",
                    limit=rule.limit, actual=hotel.price_per_night,
                ))
                requires_approval = requires_approval or rule.allow_approval

    flight_rules = [r for r in rules.rules if r.category == "flight" and _matches(r, user, request)]
    for rule in flight_rules:
        for flight in options.flights:
            if rule.limit is not None and flight.price > rule.limit:
                violations.append(Violation(
                    rule_id=rule.id, category="flight", severity=rule.severity,
                    message=f"{flight.flight_no} 票价 {flight.price} 超过标准 {rule.limit}",
                    limit=rule.limit, actual=flight.price,
                ))
                requires_approval = requires_approval or rule.allow_approval
            allowed_cabins = rule.constraint.get("cabin", [])
            if allowed_cabins and flight.cabin not in allowed_cabins:
                violations.append(Violation(
                    rule_id=rule.id, category="flight", severity=rule.severity,
                    message=f"{flight.flight_no} 舱位 {flight.cabin} 不符合标准",
                ))
                requires_approval = requires_approval or rule.allow_approval

    passed = not any(v.severity == "block" for v in violations)
    return PolicyResult(passed=passed, requires_approval=requires_approval,
                        violations=violations, policy_version=rules.version)
```

`config/policies/demo-company.yaml`：

```yaml
version: "2026.1"
tenant_id: demo-company
defaults:
  flight: { cabin: economy, max_price: 2000 }
  hotel: { max_price_per_night: 600 }
rules:
  - id: hotel-standard-L1-L2
    match: { employee_level: ["L1", "L2"] }
    category: hotel
    limit: 500
    severity: block
    allow_approval: true
  - id: hotel-standard-L3
    match: { employee_level: ["L3"] }
    category: hotel
    limit: 700
    severity: warn
    allow_approval: false
  - id: flight-cabin-L1-L2
    match: { employee_level: ["L1", "L2"] }
    category: flight
    constraint: { cabin: ["economy"] }
    severity: warn
    allow_approval: false
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_policy.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add config/policies src/itinerary_agent/control tests/test_policy.py
git commit -m "feat: add travel policy rules and evaluator"
```

---

### Task 19：Action Guard 与审计

**Files:**
- Create: `src/itinerary_agent/control/guard.py`
- Create: `src/itinerary_agent/control/audit.py`
- Create: `src/itinerary_agent/control/service.py`
- Test: `tests/test_guard.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_guard.py
from itinerary_agent.control.guard import guard_action
from itinerary_agent.domain.models import ApprovalStatus, GuardResult, TaskSnapshot, TaskStatus


def test_book_requires_confirmation():
    snapshot = TaskSnapshot(task_id="t", status=TaskStatus.EXECUTING, revision=1,
                            policy_passed=True, confirmed=False)
    result = guard_action("book_flight", snapshot, roles=["employee"])
    assert result.allowed is False
    assert result.code == "CONFIRMATION_REQUIRED"


def test_book_allowed_when_confirmed_and_approved():
    snapshot = TaskSnapshot(task_id="t", status=TaskStatus.EXECUTING, revision=1,
                            policy_passed=False, requires_approval=True,
                            approval_status=ApprovalStatus.APPROVED, confirmed=True)
    assert guard_action("book_hotel", snapshot, roles=["employee"]).allowed is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_guard.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`control/guard.py`：

```python
from itinerary_agent.domain.models import (ApprovalStatus, GuardResult, TaskSnapshot,
                                          TaskStatus)


def guard_action(action: str, snapshot: TaskSnapshot, roles: list[str]) -> GuardResult:
    if snapshot.status in {TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED}:
        return GuardResult(allowed=False, code="GUARD_DENIED", message="任务已结束")
    if action.startswith("search_") or action in {"get_user_profile", "get_policy_rules"}:
        return GuardResult(allowed=True, code="OK", message="read allowed")
    if action == "submit_approval":
        if not snapshot.policy_passed and not snapshot.requires_approval:
            return GuardResult(allowed=False, code="POLICY_BLOCKED", message="不可审批")
        return GuardResult(allowed=True, code="OK", message="approval allowed")
    if action.startswith("book_"):
        if not snapshot.confirmed:
            return GuardResult(allowed=False, code="CONFIRMATION_REQUIRED", message="需要用户确认")
        if snapshot.policy_passed is None:
            return GuardResult(allowed=False, code="POLICY_BLOCKED", message="未完成差标校验")
        if snapshot.requires_approval and snapshot.approval_status != ApprovalStatus.APPROVED:
            return GuardResult(allowed=False, code="APPROVAL_REQUIRED", message="需要审批通过")
        if snapshot.policy_passed is False and not snapshot.requires_approval:
            return GuardResult(allowed=False, code="POLICY_BLOCKED", message="差标不允许下单")
        return GuardResult(allowed=True, code="OK", message="booking allowed")
    return GuardResult(allowed=False, code="GUARD_DENIED", message="未知动作")
```

`control/audit.py`：

```python
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from itinerary_agent.infra.db import Database


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    async def record(self, trace_id: str, task_id: str | None, actor: str, action: str,
                     inputs: dict, rule_ids: list[str], policy_version: str,
                     decision: str, reason: str) -> None:
        await self.db.execute(
            "INSERT INTO audit_log (decision_id, trace_id, task_id, actor, action, inputs_hash, "
            "rule_ids, policy_version, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid4().hex, trace_id, task_id, actor, action,
             hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
             json.dumps(rule_ids), policy_version, decision, reason,
             datetime.now(timezone.utc).isoformat()),
        )
```

`control/service.py`：

```python
from itinerary_agent.control.audit import AuditLog
from itinerary_agent.control.guard import guard_action
from itinerary_agent.control.policy import check_policy
from itinerary_agent.control.rules import PolicyRules
from itinerary_agent.domain.models import (GuardResult, PolicyResult, RequestContext,
                                          SearchResults, TaskSnapshot, TripRequest,
                                          UserProfile)


class ControlService:
    def __init__(self, rules: PolicyRules, audit: AuditLog):
        self.rules = rules
        self.audit = audit

    def check_policy(self, request: TripRequest, options: SearchResults,
                     user: UserProfile) -> PolicyResult:
        return check_policy(request, options, user, self.rules)

    def guard(self, ctx: RequestContext, action: str, snapshot: TaskSnapshot) -> GuardResult:
        return guard_action(action, snapshot, ctx.roles)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_guard.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/control/guard.py src/itinerary_agent/control/audit.py tests/test_guard.py
git commit -m "feat: add action guard and audit log"
```

---

### Task 20：Mock 审批、审批工具与轮询恢复

**Files:**
- Create: `src/itinerary_agent/adapters/mock/approval.py`
- Modify: `src/itinerary_agent/tools/builtin.py`
- Create: `src/itinerary_agent/orchestration/approval_poller.py`
- Modify: `src/itinerary_agent/infra/container.py`
- Test: `tests/test_approval.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_approval.py
from itinerary_agent.adapters.mock.approval import MockApprovalSystem
from itinerary_agent.infra.db import Database


async def test_approval_can_be_rejected(tmp_path):
    db = Database(tmp_path / "a.db")
    await db.connect()
    approval = MockApprovalSystem(db, auto_approve_delay=999)
    ref = await approval.submit("t1", 1, {"plan": "x"})
    assert ref.status.value == "pending"
    await approval.decide(ref.approval_id, "rejected", "超标")
    updated = await approval.get(ref.approval_id)
    assert updated.status.value == "rejected"
    assert updated.comment == "超标"
    await db.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_approval.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`adapters/mock/approval.py`：

```python
import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from itinerary_agent.domain.models import ApprovalRef
from itinerary_agent.infra.db import Database


class MockApprovalSystem:
    def __init__(self, db: Database, auto_approve_delay: float = 5.0):
        self.db = db
        self.delay = auto_approve_delay
        self._tasks: set[asyncio.Task] = set()

    async def submit(self, task_id: str, revision: int, payload: dict) -> ApprovalRef:
        existing = await self.db.fetchone(
            "SELECT approval_id FROM approvals WHERE task_id = ? AND revision = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (task_id, revision),
        )
        if existing:
            return await self.get(existing["approval_id"])
        approval_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "INSERT INTO approvals (approval_id, task_id, revision, status, comment, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (approval_id, task_id, revision, "pending", None, now, now),
        )
        if self.delay < 900:
            timer = asyncio.create_task(self._auto_approve(approval_id))
            self._tasks.add(timer)
            timer.add_done_callback(self._tasks.discard)
        return await self.get(approval_id)

    async def _auto_approve(self, approval_id: str) -> None:
        await asyncio.sleep(self.delay)
        await self.decide(approval_id, "approved", "自动通过")

    async def decide(self, approval_id: str, status: str, comment: str) -> None:
        await self.db.execute(
            "UPDATE approvals SET status = ?, comment = ?, updated_at = ? WHERE approval_id = ?",
            (status, comment, datetime.now(timezone.utc).isoformat(), approval_id),
        )

    async def get(self, approval_id: str) -> ApprovalRef:
        row = await self.db.fetchone("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,))
        return ApprovalRef(approval_id=row["approval_id"], status=row["status"],
                           comment=row["comment"], submitted_at=datetime.fromisoformat(row["created_at"]))
```

`tools/builtin.py` 增加审批工具：

```python
SUBMIT_APPROVAL = ToolSpec(
    name="submit_approval", description="提交差旅审批", side_effect="write", risk="high",
    input_schema={"type": "object", "properties": {
        "task_id": {"type": "string"}, "revision": {"type": "integer"},
        "payload": {"type": "object"}}, "required": ["task_id", "revision", "payload"]},
    output_schema={"type": "object"},
)
GET_APPROVAL = ToolSpec(
    name="get_approval_status", description="查询审批状态", side_effect="read", risk="low",
    input_schema={"type": "object", "properties": {"approval_id": {"type": "string"}},
                  "required": ["approval_id"]},
    output_schema={"type": "object"},
)

def register_approval_tools(registry, approvals):
    async def submit_approval(ctx, args):
        ref = await approvals.submit(args["task_id"], args["revision"], args["payload"])
        return ref.model_dump(mode="json")

    async def get_approval_status(ctx, args):
        ref = await approvals.get(args["approval_id"])
        return ref.model_dump(mode="json")

    registry.register(SUBMIT_APPROVAL, submit_approval)
    registry.register(GET_APPROVAL, get_approval_status)
    return registry
```

`orchestration/approval_poller.py`：

```python
import asyncio

from itinerary_agent.domain.models import ApprovalStatus, Decision, RequestContext


class ApprovalPoller:
    def __init__(self, db, approvals, orchestrator, interval: float = 2.0):
        self.db = db
        self.approvals = approvals
        self.orchestrator = orchestrator
        self.interval = interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            rows = await self.db.fetchall(
                "SELECT a.approval_id, a.task_id, a.status, t.tenant_id, t.user_id "
                "FROM approvals a JOIN tasks t ON t.task_id = a.task_id "
                "WHERE t.status = 'WAITING_APPROVAL' AND a.status IN ('approved', 'rejected')"
            )
            for row in rows:
                await self.db.execute(
                    "UPDATE tasks SET status = 'EXECUTING' WHERE task_id = ?",
                    (row["task_id"],),
                )
                ctx = RequestContext(
                    trace_id=f"approval-{row['task_id']}", tenant_id=row["tenant_id"],
                    user_id=row["user_id"], session_id="approval",
                )
                decision = Decision(
                    action="continue",
                    approval_status=ApprovalStatus(row["status"]),
                )
                async for _ in self.orchestrator.resume(ctx, row["task_id"], decision):
                    pass
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_approval.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/adapters/mock/approval.py src/itinerary_agent/tools/builtin.py src/itinerary_agent/orchestration/approval_poller.py tests/test_approval.py
git commit -m "feat: add mock approval system and tools"
```

---

### Task 21：审批节点、下单工具与幂等

**Files:**
- Create: `src/itinerary_agent/adapters/mock/booking.py`
- Create: `src/itinerary_agent/orchestration/nodes/policy.py`
- Create: `src/itinerary_agent/orchestration/nodes/approval.py`
- Create: `src/itinerary_agent/orchestration/nodes/book.py`
- Modify: `src/itinerary_agent/tools/builtin.py`
- Modify: `src/itinerary_agent/orchestration/graph.py`
- Test: `tests/test_booking_idempotency.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_booking_idempotency.py
from itinerary_agent.adapters.mock.booking import MockBookingSystem
from itinerary_agent.infra.db import Database


async def test_booking_is_idempotent(tmp_path):
    db = Database(tmp_path / "b.db")
    await db.connect()
    booking = MockBookingSystem(db)
    first = await booking.book("book_flight", "t1:1:1", {"option_id": "f1"})
    second = await booking.book("book_flight", "t1:1:1", {"option_id": "f1"})
    assert first["booking_id"] == second["booking_id"]
    assert first["replayed"] is False
    assert second["replayed"] is True
    await db.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_booking_idempotency.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`adapters/mock/booking.py`：

```python
import json
from uuid import uuid4

from itinerary_agent.infra.db import Database


class MockBookingSystem:
    def __init__(self, db: Database):
        self.db = db

    async def book(self, kind: str, key: str, payload: dict) -> dict:
        row = await self.db.fetchone("SELECT result FROM idempotency WHERE key = ?", (key,))
        if row:
            return {**json.loads(row["result"]), "replayed": True}
        result = {"booking_id": f"{kind}-{uuid4().hex[:8]}", "status": "confirmed", "replayed": False}
        await self.db.execute("INSERT INTO idempotency (key, result, created_at) VALUES (?, ?, ?)",
                              (key, json.dumps({k: v for k, v in result.items() if k != "replayed"}),
                               "2026-10-21T00:00:00+00:00"))
        return result
```

`orchestration/nodes/policy.py`：

```python
from itinerary_agent.domain.models import PolicyResult, SearchResults, TripRequest, UserProfile


async def policy_check(state: dict, deps) -> dict:
    request = TripRequest.model_validate(state["request"])
    options = SearchResults.model_validate(state["options"])
    profile = await deps.get_user_profile(state)
    result: PolicyResult = deps.control.check_policy(request, options, profile, deps.rules)
    await deps.audit.record(state["trace_id"], state["task_id"], state["user_id"],
                            "check_policy", state["options"],
                            [v.rule_id for v in result.violations], result.policy_version,
                            "pass" if result.passed else "block", "policy evaluation")
    return {"policy_result": result.model_dump(mode="json"), "status": "EXECUTING"}
```

`orchestration/nodes/approval.py`：

```python
from langgraph.types import interrupt

from itinerary_agent.domain.models import HumanRequest, HumanRequestType


async def request_approval(state: dict, deps) -> dict:
    result = await deps.guarded_invoke(state, "submit_approval", "submit_approval", {
        "task_id": state["task_id"], "revision": state["revision"],
        "payload": {"request": state["request"], "options": state["options"]},
    })
    if not result.ok:
        return {"status": "FAILED", "error": result.error.model_dump()}
    approval = result.data
    decision = interrupt({
        "kind": "approval",
        "approval_id": approval["approval_id"],
        "message": "等待审批结果。",
    })
    status = (decision or {}).get("status", "pending")
    approval = {**approval, "status": status}
    if status == "rejected":
        human = HumanRequest(
            type=HumanRequestType.APPROVAL_REJECTED,
            message=(decision or {}).get("comment", "审批驳回，请修改方案。"),
        )
        return {"approval": approval, "status": "WAITING_HUMAN",
                "pending_human": human.model_dump(mode="json")}
    return {"approval": approval, "status": "EXECUTING"}
```

`orchestration/nodes/book.py`：

```python
async def book(state: dict, deps) -> dict:
    selected = state.get("selected", {})
    if selected.get("flight_id"):
        result = await deps.guarded_invoke(state, "book_flight", "book_flight", {
            "option_id": selected["flight_id"],
            "idempotency_key": f"{state['task_id']}:book_flight:{state['revision']}",
        })
        if not result.ok:
            return {"status": "WAITING_HUMAN",
                    "pending_human": {"type": "clarify", "message": result.error.message,
                                      "options": []}}
    if selected.get("hotel_id"):
        result = await deps.guarded_invoke(state, "book_hotel", "book_hotel", {
            "option_id": selected["hotel_id"],
            "idempotency_key": f"{state['task_id']}:book_hotel:{state['revision']}",
        })
        if not result.ok:
            return {"status": "WAITING_HUMAN",
                    "pending_human": {"type": "clarify", "message": result.error.message,
                                      "options": []}}
    return {"status": "COMPLETED"}
```

`tools/builtin.py` 增加：

```python
BOOK_FLIGHT = ToolSpec(
    name="book_flight", description="预订机票", side_effect="write", risk="high",
    input_schema={"type": "object", "properties": {
        "option_id": {"type": "string"}, "idempotency_key": {"type": "string"}},
        "required": ["option_id", "idempotency_key"]}, output_schema={"type": "object"},
)
BOOK_HOTEL = ToolSpec(
    name="book_hotel", description="预订酒店", side_effect="write", risk="high",
    input_schema={"type": "object", "properties": {
        "option_id": {"type": "string"}, "idempotency_key": {"type": "string"}},
        "required": ["option_id", "idempotency_key"]}, output_schema={"type": "object"},
)

def register_booking_tools(registry, booking):
    async def book_flight(ctx, args):
        return await booking.book("book_flight", args["idempotency_key"], args)

    async def book_hotel(ctx, args):
        return await booking.book("book_hotel", args["idempotency_key"], args)

    registry.register(BOOK_FLIGHT, book_flight)
    registry.register(BOOK_HOTEL, book_hotel)
    return registry
```

`graph.py` 路由：

```python
from itinerary_agent.orchestration.nodes.approval import request_approval
from itinerary_agent.orchestration.nodes.book import book
from itinerary_agent.orchestration.nodes.policy import policy_check


def route_after_policy(state: dict) -> str:
    result = state.get("policy_result") or {}
    if result.get("requires_approval"):
        return "approval"
    return "confirm"


def route_after_confirm(state: dict) -> str:
    if state["status"] == "CANCELLED":
        return "respond"
    if state["status"] == "PLANNING":
        return "plan"
    return "book"

graph.add_node("policy", partial(policy_check, deps=deps))
graph.add_node("approval", partial(request_approval, deps=deps))
graph.add_node("book", partial(book, deps=deps))
graph.add_edge("search", "policy")
graph.add_conditional_edges("policy", route_after_policy,
                            {"approval": "approval", "confirm": "confirm", "respond": "respond"})
graph.add_edge("approval", "confirm")
graph.add_conditional_edges("confirm", route_after_confirm,
                            {"book": "book", "respond": "respond", "plan": "plan"})
graph.add_edge("book", "respond")
```

`infra/container.py` 在 `start()` 中完成 M4 装配（替换原来的最少装配）：

```python
from pathlib import Path

from itinerary_agent.adapters.mock.approval import MockApprovalSystem
from itinerary_agent.adapters.mock.booking import MockBookingSystem
from itinerary_agent.adapters.mock.inventory import MockFlightInventory, MockHotelInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.control.audit import AuditLog
from itinerary_agent.control.rules import load_rules
from itinerary_agent.control.service import ControlService
from itinerary_agent.orchestration.approval_poller import ApprovalPoller
from itinerary_agent.tools.builtin import (build_builtin_registry, register_approval_tools,
                                           register_booking_tools)
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService

async def start(self):
    await self.db.connect()
    self.conn = await aiosqlite.connect(self.settings.sqlite_path)
    self.checkpointer = AsyncSqliteSaver(self.conn)

    registry = build_builtin_registry(
        ToolRegistry(), MockFlightInventory(), MockHotelInventory(), MockUserDirectory()
    )
    self.approvals = MockApprovalSystem(self.db, self.settings.mock_approval_delay_seconds)
    self.booking = MockBookingSystem(self.db)
    register_approval_tools(registry, self.approvals)
    register_booking_tools(registry, self.booking)
    self.tools = ToolService(registry)

    self.audit = AuditLog(self.db)
    self.rules = load_rules(Path("config/policies/demo-company.yaml"))
    self.control = ControlService(self.rules, self.audit)
    self.orchestrator = self.build_orchestrator()
    self.poller = ApprovalPoller(self.db, self.approvals, self.orchestrator)
    self.poller.start()

async def stop(self):
    if getattr(self, "poller", None) is not None:
        await self.poller.stop()
    await self.db.close()
    if self.conn is not None:
        await self.conn.close()
```

`build_orchestrator` 传入 `rules=rules, audit=self.audit`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_booking_idempotency.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/adapters/mock/booking.py src/itinerary_agent/orchestration/nodes src/itinerary_agent/tools/builtin.py src/itinerary_agent/orchestration/graph.py tests/test_booking_idempotency.py
git commit -m "feat: add policy, approval and booking nodes"
```

---

### Task 22：revision 修改与审批驳回

**Files:**
- Modify: `src/itinerary_agent/orchestration/nodes/confirm.py`
- Modify: `src/itinerary_agent/orchestration/service.py`
- Test: `tests/test_amendment.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_amendment.py
from itinerary_agent.domain.models import Decision, TripRequest


def test_amendment_clears_downstream():
    from itinerary_agent.orchestration.service import apply_amendment

    state = {
        "revision": 1, "request": {"destination_city": "北京"},
        "options": {"flights": [{"option_id": "f1"}], "hotels": []},
        "policy_result": {"passed": True}, "policy_refs": ["c1"],
        "approval": {"approval_id": "a1"}, "selected": {"flight_id": "f1"},
        "confirmed": True, "status": "EXECUTING",
    }
    updated = apply_amendment(state, TripRequest(destination_city="上海"))
    assert updated["revision"] == 2
    assert updated["options"] == {"flights": [], "hotels": []}
    assert updated["approval"] is None
    assert updated["confirmed"] is False
    assert updated["status"] == "PLANNING"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_amendment.py -v`
Expected: FAIL — function not found

- [ ] **Step 3: 写实现**

`service.py` 增加：

```python
def apply_amendment(state: dict, request: TripRequest) -> dict:
    return {
        **state,
        "request": request.model_dump(mode="json"),
        "revision": state["revision"] + 1,
        "options": {"flights": [], "hotels": []},
        "policy_result": None,
        "policy_refs": [],
        "approval": None,
        "selected": {},
        "confirmed": False,
        "pending_amendment": None,
        "status": "PLANNING",
    }
```

`service.resume` 在流式执行前处理修改：

```python
if decision.action == "modify" and decision.amended_request is not None:
    snapshot = await self.graph.aget_state(config)
    amended = apply_amendment(snapshot.values, decision.amended_request)
    await self.graph.aupdate_state(config, amended)
    async for update in self.graph.astream(Command(resume={"action": "modify"}),
                                           config=config, stream_mode="updates"):
        for node, _ in update.items():
            yield Event(type="progress", data={"task_id": task_id, "node": node})
    final = await self.graph.aget_state(config)
    await self._upsert_task(final.values, final.values["status"])
    yield Event(type="result", data={"task_id": task_id, "status": final.values["status"]})
    return
```

`confirm.py` 处理修改并返回规划状态：

```python
if isinstance(decision, dict) and decision.get("action") == "modify":
    return {"status": "PLANNING", "confirmed": False}
if isinstance(decision, dict) and decision.get("action") == "cancel":
    return {"status": "CANCELLED"}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_amendment.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/orchestration tests/test_amendment.py
git commit -m "feat: support amendment and revision invalidation"
```

---

## M5：可观测、UI 与端到端验收

### Task 23：全链路 span 与 trace 查询

**Files:**
- Create: `src/itinerary_agent/observability/query.py`
- Modify: `src/itinerary_agent/api/routes.py`
- Modify: `src/itinerary_agent/api/app.py`
- Test: `tests/test_trace_view.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_trace_view.py
from itinerary_agent.infra.db import Database
from itinerary_agent.observability.query import load_trace_tree


async def test_trace_tree(tmp_path):
    db = Database(tmp_path / "t.db")
    await db.connect()
    await db.execute("INSERT INTO spans (span_id, trace_id, parent_span_id, name, layer, status, "
                     "start_time, duration_ms, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ("s1", "t1", None, "gateway.http", "gateway", "ok",
                      "2026-10-21T00:00:00+00:00", 1.0, "{}"))
    await db.execute("INSERT INTO spans (span_id, trace_id, parent_span_id, name, layer, status, "
                     "start_time, duration_ms, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     ("s2", "t1", "s1", "tool.search_flights", "tools", "ok",
                      "2026-10-21T00:00:01+00:00", 2.0, "{}"))
    tree = await load_trace_tree(db, "t1")
    assert tree[0]["name"] == "gateway.http"
    assert tree[0]["children"][0]["name"] == "tool.search_flights"
    await db.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_trace_view.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: 写实现**

`observability/query.py`：

```python
import json

from itinerary_agent.infra.db import Database


async def load_trace_tree(db: Database, trace_id: str) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time", (trace_id,)
    )
    nodes = {}
    roots = []
    for row in rows:
        node = {
            "span_id": row["span_id"], "parent_span_id": row["parent_span_id"],
            "name": row["name"], "layer": row["layer"], "status": row["status"],
            "duration_ms": row["duration_ms"],
            "attributes": json.loads(row["attributes"]), "children": [],
        }
        nodes[node["span_id"]] = node
    for node in nodes.values():
        parent = nodes.get(node["parent_span_id"])
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots
```

`routes.py` 增加：

```python
from itinerary_agent.observability.query import load_trace_tree
from fastapi.responses import HTMLResponse

@router.get("/traces/{trace_id}")
async def trace_json(trace_id: str):
    return {"trace_id": trace_id, "spans": await load_trace_tree(container.db, trace_id)}

@router.get("/traces/{trace_id}/view", response_class=HTMLResponse)
async def trace_view(trace_id: str):
    tree = await load_trace_tree(container.db, trace_id)

    def render(nodes, depth=0):
        out = []
        for n in nodes:
            out.append(f"<div style='margin-left:{depth * 20}px'>"
                       f"[{n['layer']}] {n['name']} — {n['status']} "
                       f"({n['duration_ms']:.1f}ms)</div>")
            out.extend(render(n["children"], depth + 1))
        return out

    return "<html><body><h2>Trace " + trace_id + "</h2>" + "".join(render(tree)) + "</body></html>"
```

**埋点接入点**（在对应类中包裹实际调用）：

```python
# api/routes.py：每次请求
async with container.traces.span("gateway.http", "gateway", route="/chat"):
    ...

# tools/service.py：每次工具调用
async with self.traces.span(f"tool.{name}", "tools", tool_name=name,
                            side_effect=spec.side_effect, risk=spec.risk):
    ...

# model_gateway/gateway.py：每次模型调用
async with self.traces.span(f"model.{ctx.purpose}", "model",
                            model=model, prompt_version=ctx.prompt_version):
    ...

# knowledge/service.py：每次检索
async with self.traces.span("knowledge.search_policy", "knowledge",
                            tenant_id=ctx.tenant_id, top_k=top_k):
    ...

# control/service.py：每次差标/准入
async with self.traces.span("control.check_policy", "control",
                            tenant_id=ctx.tenant_id):
    ...
```

为支持上述埋点，`ToolService`、`OpenAIChatGateway`、`KnowledgeService`、`ControlService` 的构造函数都增加 `traces` 参数，由容器传入同一个 `TraceRecorder`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_trace_view.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/observability/query.py src/itinerary_agent/api/routes.py tests/test_trace_view.py
git commit -m "feat: add trace query and vertical view"
```

---

### Task 24：最小 Web 聊天页与手动审批接口

**Files:**
- Modify: `src/itinerary_agent/api/app.py`
- Modify: `src/itinerary_agent/api/routes.py`
- Create: `src/itinerary_agent/api/static/chat.html`
- Test: `tests/test_admin_approval.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_admin_approval.py
from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container


def test_admin_reject(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "admin.db")
    container = build_container(settings)
    app = create_app(container)
    with TestClient(app) as client:
        resp = client.post("/admin/approvals/missing/reject",
                           headers={"X-Mock-User": "u002"}, json={"comment": "超标"})
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_admin_approval.py -v`
Expected: FAIL — 404 route not found

- [ ] **Step 3: 写实现**

`routes.py` 增加：

```python
from fastapi.responses import JSONResponse
from pydantic import BaseModel

class AdminDecision(BaseModel):
    comment: str = ""

@router.post("/admin/approvals/{approval_id}/approve")
async def approve(approval_id: str, payload: AdminDecision, request: Request):
    ctx = build_context(request)
    if "admin" not in ctx.roles and "approver" not in ctx.roles:
        return {"error": "forbidden"}
    await container.approvals.decide(approval_id, "approved", payload.comment)
    return {"ok": True}

@router.post("/admin/approvals/{approval_id}/reject")
async def reject(approval_id: str, payload: AdminDecision, request: Request):
    ctx = build_context(request)
    if "admin" not in ctx.roles and "approver" not in ctx.roles:
        return {"error": "forbidden"}
    row = await container.db.fetchone("SELECT approval_id FROM approvals WHERE approval_id = ?", (approval_id,))
    if row is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    await container.approvals.decide(approval_id, "rejected", payload.comment)
    return {"ok": True}
```

`app.py` 增加首页：

```python
from fastapi.responses import FileResponse
from pathlib import Path

@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "chat.html")
```

`api/static/chat.html`：

```html
<!doctype html>
<html lang="zh-CN">
<body>
<h2>差旅助手</h2>
<textarea id="msg" rows="3" cols="60">下周二去北京出差两天，住王府井附近，预算 1000 元</textarea><br>
<button onclick="send()">发送</button>
<pre id="out"></pre>
<script>
async function send() {
  const res = await fetch('/chat', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                   body: JSON.stringify({message: document.getElementById('msg').value})});
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  while (true) {
    const {done, value} = await reader.read();
    if (done) break;
    document.getElementById('out').textContent += decoder.decode(value);
  }
}
</script>
</body>
</html>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/test_admin_approval.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/itinerary_agent/api tests/test_admin_approval.py
git commit -m "feat: add minimal web page and admin approval"
```

---

### Task 25：端到端场景与 import 边界测试

**Files:**
- Create: `tests/scenarios.py`
- Create: `tests/test_scenarios.py`
- Create: `tests/test_import_boundaries.py`
- Test: 上述两个文件

- [ ] **Step 1: 写场景测试**

`tests/scenarios.py` 提供 `make_app(tmp_path, script)`：用 `ScriptedModelGateway`、mock 适配器、临时 SQLite 构造 app。`tests/test_scenarios.py` 覆盖：

```python
async def test_scenario_over_policy_then_approve(tmp_path):
    app, client = make_app(tmp_path, [
        '{"destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_hotels"]}',
        '"方案已确认"',
    ])
    # 1. /chat 到 interrupt
    # 2. /tasks/{id}/resume 选择超标准酒店
    # 3. /admin/approvals/{id}/approve
    # 4. 轮询 /tasks/{id} 直到 COMPLETED
```

其余场景在同一个 `tests/test_scenarios.py` 中实现，函数名与断言如下：

| 场景 | 测试函数 | 关键断言 |
|---|---|---|
| 正常链路 | `test_normal_booking` | 最终 `status == "COMPLETED"`，mock booking 表有记录 |
| 超标准 | `test_over_policy_requires_approval` | 首次 interrupt 的 `human_request["message"]` 含"不符合差标"；修改预算后继续 |
| 审批驳回 | `test_approval_rejected` | 管理员 reject 后任务为 `WAITING_HUMAN`；携带驳回意见 |
| 中途修改 | `test_amendment_invalidates_downstream` | `revision` 从 1 变 2；`options`、`approval`、`confirmed` 被清空 |
| 查询无结果 | `test_no_results_asks_human` | 库存返回空时任务停在 `WAITING_HUMAN`，提示放宽条件 |
| 暂停/恢复/取消 | `test_pause_resume_cancel` | pause 后 `PAUSED`；resume 回到原状态；cancel 为 `CANCELLED` |
| 工具失败 / RAG 降级 | `test_tool_failure_and_rag_degraded` | 工具错误映射为 `TOOL_UNAVAILABLE`；知识返回空时主流程继续 |
| 未审批下单 | `test_booking_without_approval_denied` | Guard 返回 `APPROVAL_REQUIRED`，`audit_log` 有记录 |

- [ ] **Step 2: 写 import 边界测试**

```python
# tests/test_import_boundaries.py
import ast
from pathlib import Path


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_api_does_not_import_langgraph_or_openai():
    for path in Path("src/itinerary_agent/api").rglob("*.py"):
        names = imports(path)
        assert not any(n.startswith("langgraph") for n in names), path
        assert not any(n.startswith("openai") for n in names), path


def test_orchestration_does_not_import_model_sdk():
    for path in Path("src/itinerary_agent/orchestration").rglob("*.py"):
        names = imports(path)
        assert not any(n.startswith("openai") for n in names), path
        assert not any(n.startswith("pymilvus") for n in names), path
```

- [ ] **Step 3: 运行全部测试**

Run: `uv run pytest -v`
Expected: 全部 PASS；`@pytest.mark.live` 默认跳过。

- [ ] **Step 4: 修复失败项并重复**

按失败输出逐个修复；不得用 skip 掩盖非 live 测试。

- [ ] **Step 5: 提交**

```bash
git add tests
git commit -m "test: add end-to-end scenarios and boundary checks"
```

---

### Task 26：运行文档与最终验收

**Files:**
- Modify: `readme.md`
- Create: `.env.example`
- Test: 手动验收

- [ ] **Step 1: 写 `.env.example`**

```dotenv
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=
MODEL_LIGHT=deepseek-chat
MODEL_STANDARD=deepseek-chat
MODEL_REASONING=deepseek-reasoner
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_API_KEY=
MILVUS_URI=http://127.0.0.1:19530
MODEL_MODE=scripted
ADAPTER_MODE=mock
```

- [ ] **Step 2: 更新 readme.md**

在原有设计说明后追加：

```markdown
## 本地运行

1. 安装依赖：`uv sync --dev`
2. 复制 `.env.example` 为 `.env`，填入 API Key
3. 启动：`uv run uvicorn itinerary_agent.main:app --reload`
4. 打开 http://127.0.0.1:8000/
5. 测试：`uv run pytest -v`
```

- [ ] **Step 3: 手动验收**

- 正常链路跑通；
- 超标准触发 interrupt；
- 驳回后能修改并重走；
- `/traces/{trace_id}/view` 能看到七层 span；
- 停止后重启，任务可从 Checkpoint 恢复。

- [ ] **Step 4: 最终提交**

```bash
git add readme.md .env.example
git commit -m "docs: add local run instructions"
```

---

## 执行顺序

```text
M0 Task 1-5 → M1 Task 6-8 → M2 Task 9-13 → M3 Task 14-17
→ M4 Task 18-22 → M5 Task 23-26
```

每个 Task 完成后必须测试通过再提交；M3 的 live 测试需要真实 API Key，默认不运行。
