"""独立的 mock 外部依赖服务。

把用户、库存、审批、下单从进程内 mock 拆成 HTTP 服务，用于验证真实
网络边界、超时/重试、幂等与契约测试。默认仍由 `ADAPTER_MODE=mock`
使用进程内实现；`ADAPTER_MODE=http` 时切换到这里。

运行：
uv run uvicorn --app-dir src itinerary_agent.mock_services.deps:app --port 9003
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from itinerary_agent.adapters.mock.inventory import (
    MockFlightInventory,
    MockHotelInventory,
)
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.domain.models import ApprovalRef, ApprovalStatus
from itinerary_agent.infra.config import Settings
from itinerary_agent.observability.telemetry import setup_telemetry


class BookingRequest(BaseModel):
    kind: Literal["book_flight", "book_hotel"]
    idempotency_key: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


class ApprovalSubmit(BaseModel):
    task_id: str
    revision: int
    payload: dict = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    status: Literal["approved", "rejected"]
    comment: str = ""


class InMemoryApprovals:
    """按 task_id + revision 幂等；只用于本地契约测试。"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._by_id: dict[str, dict] = {}
        self._by_revision: dict[tuple[str, int], str] = {}

    async def submit(self, task_id: str, revision: int,
                     payload: dict) -> dict:
        async with self._lock:
            existing = self._by_revision.get((task_id, revision))
            if existing:
                return dict(self._by_id[existing])
            approval_id = uuid4().hex
            row = {
                "approval_id": approval_id,
                "task_id": task_id,
                "revision": revision,
                "status": "pending",
                "comment": None,
                "payload": payload,
                "submitted_at": datetime.now(UTC),
            }
            self._by_id[approval_id] = row
            self._by_revision[(task_id, revision)] = approval_id
            return dict(row)

    async def get(self, approval_id: str) -> dict | None:
        row = self._by_id.get(approval_id)
        return dict(row) if row else None

    async def decide(self, approval_id: str, status: str,
                     comment: str) -> dict | None:
        async with self._lock:
            row = self._by_id.get(approval_id)
            if row is None:
                return None
            row["status"] = status
            row["comment"] = comment
            return dict(row)

    async def list(self, status: str | None = None) -> list[dict]:
        return [
            dict(row) for row in self._by_id.values()
            if status is None or row["status"] == status
        ]


class InMemoryBookings:
    """幂等下单；同一 key 返回第一次结果并标记 replayed。"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._results: dict[str, dict] = {}

    async def book(self, kind: str, key: str, payload: dict) -> dict:
        async with self._lock:
            if key in self._results:
                return {**self._results[key], "replayed": True}
            result = {
                "booking_id": f"{kind}-{uuid4().hex[:8]}",
                "status": "confirmed",
                "payload": payload,
            }
            self._results[key] = result
            return {**result, "replayed": False}


def create_deps_app(*, telemetry: bool = False) -> FastAPI:
    app = FastAPI(title="Itinerary Mock Dependencies")
    if telemetry:
        # 作为独立服务导出 server span，Tempo Service Graph 才能配对
        # api -> mock-deps 的 HTTPX client span。
        setup_telemetry(Settings(), app)
    users = MockUserDirectory()
    flights = MockFlightInventory()
    hotels = MockHotelInventory()
    approvals = InMemoryApprovals()
    bookings = InMemoryBookings()

    @app.middleware("http")
    async def inject_fault(request: Request, call_next):
        """契约/混沌测试用：X-Mock-Fault: 500|429|timeout。"""
        fault = request.headers.get("X-Mock-Fault")
        if fault == "500":
            return JSONResponse(
                status_code=500, content={"error": "injected upstream error"}
            )
        if fault == "429":
            return JSONResponse(
                status_code=429,
                content={"error": "injected rate limit"},
                headers={"Retry-After": "1"},
            )
        if fault == "timeout":
            await asyncio.sleep(2)
        return await call_next(request)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/users/{user_id}")
    async def get_user(user_id: str):
        try:
            return (await users.get(user_id)).model_dump(mode="json")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="user not found") from exc

    @app.get("/inventory/flights")
    async def search_flights(origin: str, destination: str, date: str):
        options = await flights.search(origin, destination, date)
        return {"flights": [item.model_dump(mode="json") for item in options]}

    @app.get("/inventory/hotels")
    async def search_hotels(city: str, check_in: str, check_out: str,
                            area: str | None = None):
        options = await hotels.search(city, check_in, check_out, area)
        return {"hotels": [item.model_dump(mode="json") for item in options]}

    @app.post("/bookings")
    async def create_booking(payload: BookingRequest):
        return await bookings.book(
            payload.kind, payload.idempotency_key, payload.payload
        )

    @app.post("/approvals")
    async def submit_approval(payload: ApprovalSubmit):
        row = await approvals.submit(
            payload.task_id, payload.revision, payload.payload
        )
        return ApprovalRef(
            approval_id=row["approval_id"],
            status=ApprovalStatus(row["status"]),
            submitted_at=row["submitted_at"],
        ).model_dump(mode="json")

    @app.get("/approvals/{approval_id}")
    async def get_approval(approval_id: str):
        row = await approvals.get(approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return ApprovalRef(
            approval_id=row["approval_id"],
            status=ApprovalStatus(row["status"]),
            comment=row["comment"],
            submitted_at=row["submitted_at"],
        ).model_dump(mode="json")

    @app.get("/approvals")
    async def list_approvals(status: str | None = None):
        return {"approvals": await approvals.list(status)}

    @app.post("/approvals/{approval_id}/decide")
    async def decide_approval(approval_id: str, payload: ApprovalDecision):
        row = await approvals.decide(
            approval_id, payload.status, payload.comment
        )
        if row is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return {"ok": True}

    # 便于调试：返回当前内存状态，不参与业务协议。
    @app.get("/_debug/bookings")
    async def debug_bookings():
        return {"bookings": json.loads(json.dumps(bookings._results))}

    return app


app = create_deps_app(telemetry=True)
