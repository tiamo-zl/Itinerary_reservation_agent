"""外部系统接口。

编排层/工具层只依赖这些 Protocol；mock 与真实实现都通过 infra 注入。
"""

from typing import Protocol

from itinerary_agent.domain.models import FlightOption, HotelOption, UserProfile


class UserDirectory(Protocol):
    async def get(self, user_id: str) -> UserProfile: ...


class FlightInventory(Protocol):
    async def search(self, origin: str, destination: str, date: str) -> list[FlightOption]: ...


class HotelInventory(Protocol):
    async def search(self, city: str, check_in: str, check_out: str,
                     area: str | None) -> list[HotelOption]: ...


class ApprovalStore(Protocol):
    """mock 审批系统依赖的最小持久化接口。"""

    async def find_by_task_revision(self, task_id: str,
                                    revision: int) -> dict | None: ...
    async def insert_pending(self, approval_id: str, task_id: str,
                             revision: int, payload: str,
                             created_at: str) -> int: ...
    async def get(self, approval_id: str) -> dict | None: ...
    async def decide(self, approval_id: str, status: str,
                     comment: str) -> None: ...


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> dict | None: ...
    async def put_if_absent(self, key: str, result: str,
                            created_at: str) -> int: ...
