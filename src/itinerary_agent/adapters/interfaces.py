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
