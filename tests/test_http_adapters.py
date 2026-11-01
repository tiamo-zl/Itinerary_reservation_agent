"""HTTP 适配器：协议映射、超时/重试、错误分类与幂等回放。"""

import httpx
import pytest

from itinerary_agent.adapters.http.approval import HttpApprovalSystem
from itinerary_agent.adapters.http.booking import HttpBookingSystem
from itinerary_agent.adapters.http.client import JsonHttpClient, UpstreamError
from itinerary_agent.adapters.http.inventory import (
    HttpFlightInventory,
    HttpHotelInventory,
)
from itinerary_agent.adapters.http.users import HttpUserDirectory
from itinerary_agent.mock_services.deps import create_deps_app


def _client(transport: httpx.AsyncBaseTransport,
            max_retries: int = 0) -> JsonHttpClient:
    http = httpx.AsyncClient(
        transport=transport, base_url="http://mock", timeout=1.0
    )
    return JsonHttpClient(
        "http://mock", timeout=1.0, max_retries=max_retries, client=http
    )


def _asgi() -> httpx.ASGITransport:
    return httpx.ASGITransport(app=create_deps_app())


async def test_adapters_map_protocols():
    client = _client(_asgi())
    try:
        user = await HttpUserDirectory(client).get("u001")
        assert user.employee_level == "L2"

        flights = await HttpFlightInventory(client).search(
            "上海", "北京", "2026-11-03"
        )
        assert flights[0].option_id == "f1"

        hotels = await HttpHotelInventory(client).search(
            "北京", "2026-11-03", "2026-11-05", None
        )
        assert hotels[0].price_per_night == 480.0

        booking = HttpBookingSystem(client)
        first = await booking.book("book_flight", "k1", {"option_id": "f1"})
        second = await booking.book("book_flight", "k1", {"option_id": "f1"})
        assert first["replayed"] is False
        assert second["replayed"] is True

        approvals = HttpApprovalSystem(client)
        ref = await approvals.submit("t1", 0, {"amount": 1})
        again = await approvals.submit("t1", 0, {"amount": 1})
        assert ref.approval_id == again.approval_id
        await approvals.decide(ref.approval_id, "approved", "ok")
        current = await approvals.get(ref.approval_id)
        assert current.status.value == "approved"
    finally:
        await client.close()


async def test_client_retries_5xx_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(200, json={"ok": True})

    client = _client(httpx.MockTransport(handler), max_retries=1)
    try:
        assert await client.get("/probe") == {"ok": True}
        assert calls["n"] == 2
    finally:
        await client.close()


async def test_client_maps_404_and_bad_json():
    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "missing"})

    client = _client(httpx.MockTransport(not_found))
    try:
        with pytest.raises(UpstreamError) as exc:
            await client.get("/missing")
        assert exc.value.code == "UPSTREAM_BAD_RESPONSE"
        assert exc.value.retryable is False
    finally:
        await client.close()

    def invalid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = _client(httpx.MockTransport(invalid))
    try:
        with pytest.raises(UpstreamError) as exc:
            await client.get("/bad")
        assert exc.value.code == "UPSTREAM_BAD_RESPONSE"
    finally:
        await client.close()


async def test_client_timeout_is_typed_and_retryable():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = _client(httpx.MockTransport(timeout), max_retries=1)
    try:
        with pytest.raises(UpstreamError) as exc:
            await client.get("/slow")
        assert exc.value.code == "UPSTREAM_TIMEOUT"
        assert exc.value.retryable is True
    finally:
        await client.close()
