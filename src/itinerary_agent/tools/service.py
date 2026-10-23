"""工具执行服务。

统一做参数校验和异常归一化；不在参数非法时调用 handler，
避免把坏参数传给外部系统。
"""

import jsonschema

from itinerary_agent.domain.models import RequestContext, ToolError, ToolResult
from itinerary_agent.tools.registry import ToolRegistry


class ToolService:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def invoke(self, ctx: RequestContext, name: str, args: dict) -> ToolResult:
        spec = self.registry.spec(name)
        # 校验失败直接抛出，表示调用方编程错误；业务失败才归一化为 ToolResult。
        jsonschema.validate(instance=args, schema=spec.input_schema)

        try:
            data = await self.registry.handler(name)(ctx, args)
            return ToolResult(ok=True, data=data, trace_id=ctx.trace_id)
        except Exception as exc:  # noqa: BLE001 - 工具边界必须隔离所有实现异常
            # M2 统一按可重试处理；M4 会根据具体适配器返回更细的错误码。
            return ToolResult(
                ok=False,
                trace_id=ctx.trace_id,
                error=ToolError(
                    code="TOOL_UNAVAILABLE", message=str(exc), retryable=True
                ),
            )
