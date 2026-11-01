"""HTTP 下单适配器。"""

from itinerary_agent.adapters.http.client import JsonHttpClient


class HttpBookingSystem:
    def __init__(self, client: JsonHttpClient):
        self.client = client

    async def book(self, kind: str, key: str, payload: dict) -> dict:
        # 幂等键随请求发送；外部系统负责重复请求返回同一结果。
        return await self.client.post("/bookings", {
            "kind": kind,
            "idempotency_key": key,
            "payload": payload,
        })
