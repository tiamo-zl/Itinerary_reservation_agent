import asyncio

import jsonschema
import pytest

from itinerary_agent.domain.models import RequestContext, ToolSpec
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


def _ctx(scopes: list[str] | None = None) -> RequestContext:
    return RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001",
        session_id="s", scopes=scopes or [],
    )


async def test_tool_requires_scope_and_does_not_call_handler():
    registry = ToolRegistry()
    called = False

    async def handler(ctx, args):
        nonlocal called
        called = True
        return {"ok": True}

    registry.register(
        ToolSpec(
            name="admin_tool", description="admin", side_effect="read",
            risk="low", required_scopes=["admin"],
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        handler,
    )

    result = await ToolService(registry).invoke(_ctx(["chat"]), "admin_tool", {})
    assert result.ok is False
    assert result.error.code == "TOOL_FORBIDDEN"
    assert called is False


async def test_tool_timeout_is_typed():
    registry = ToolRegistry()

    async def slow(ctx, args):
        await asyncio.sleep(1)
        return {}

    registry.register(
        ToolSpec(
            name="slow", description="slow", side_effect="read", risk="low",
            timeout_ms=10, input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        slow,
    )

    result = await ToolService(registry).invoke(_ctx(["chat"]), "slow", {})
    assert result.ok is False
    assert result.error.code == "TOOL_TIMEOUT"
    assert result.error.retryable is True


async def test_tool_output_schema_mismatch_is_not_retryable():
    registry = ToolRegistry()

    async def broken(ctx, args):
        return {"wrong": "shape"}

    registry.register(
        ToolSpec(
            name="broken", description="broken", side_effect="read",
            risk="low",
            input_schema={"type": "object"},
            output_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        ),
        broken,
    )

    result = await ToolService(registry).invoke(_ctx(["chat"]), "broken", {})
    assert result.ok is False
    assert result.error.code == "TOOL_BAD_RESPONSE"
    assert result.error.retryable is False


async def test_unknown_tool_and_handler_error_are_typed():
    registry = ToolRegistry()

    async def crash(ctx, args):
        raise RuntimeError("upstream down")

    registry.register(
        ToolSpec(
            name="crash", description="crash", side_effect="read",
            risk="low", input_schema={"type": "object"},
            output_schema={"type": "object"},
        ),
        crash,
    )
    service = ToolService(registry)

    missing = await service.invoke(_ctx(["chat"]), "missing", {})
    assert missing.error.code == "TOOL_NOT_FOUND"

    failed = await service.invoke(_ctx(["chat"]), "crash", {})
    assert failed.error.code == "TOOL_UNAVAILABLE"
    assert failed.error.retryable is True


async def test_tool_invoke_validates_and_returns(tmp_path):
    registry = ToolRegistry()

    async def echo(ctx, args):
        return {"echo": args["value"]}

    registry.register(
        ToolSpec(
            name="echo", description="echo", side_effect="read", risk="low",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            output_schema={"type": "object"},
        ),
        echo,
    )
    service = ToolService(registry)
    ctx = RequestContext(
        trace_id="t", tenant_id="demo-company", user_id="u001", session_id="s"
    )

    result = await service.invoke(ctx, "echo", {"value": "hi"})
    assert result.ok is True
    assert result.data == {"echo": "hi"}

    # 参数校验失败必须在进入 handler 之前抛出，避免带着坏参数调用外部系统。
    with pytest.raises(jsonschema.ValidationError):
        await service.invoke(ctx, "echo", {})
