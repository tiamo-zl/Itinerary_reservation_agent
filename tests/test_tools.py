import jsonschema
import pytest

from itinerary_agent.domain.models import RequestContext, ToolSpec
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


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
