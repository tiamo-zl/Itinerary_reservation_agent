"""工具执行服务。

统一做 scope、参数/输出校验、超时和异常归一化；不在参数非法时调用
handler，避免把坏参数传给外部系统。错误码是稳定契约，编排层只依赖
ToolResult，不解析异常文本。
"""

import asyncio
import logging
from time import perf_counter

import jsonschema

from itinerary_agent.domain.models import RequestContext, ToolError, ToolResult
from itinerary_agent.observability.metrics import TOOL_CALLS, TOOL_DURATION
from itinerary_agent.security.scopes import has_scope
from itinerary_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class _NullSpan:
    """没有 TraceRecorder 时的空 span。"""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class ToolService:
    def __init__(self, registry: ToolRegistry, traces=None):
        self.registry = registry
        self.traces = traces

    async def invoke(self, ctx: RequestContext, name: str, args: dict) -> ToolResult:
        # 步骤 1：解析工具定义；未知工具是装配/调用错误，不访问外部系统。
        try:
            spec = self.registry.spec(name)
        except KeyError:
            return self._fail(
                ctx, name, "TOOL_NOT_FOUND", f"unknown tool: {name}", False
            )

        # 步骤 2：scope 检查先于参数校验，避免无权限调用者探测 schema。
        missing = [
            scope for scope in spec.required_scopes
            if not has_scope(ctx, scope)
        ]
        if missing:
            return self._fail(
                ctx, name, "TOOL_FORBIDDEN",
                f"missing scopes: {', '.join(missing)}", False,
            )

        # 步骤 3：输入校验失败直接抛出，表示调用方编程错误；
        # 业务失败才归一化为 ToolResult。
        jsonschema.validate(instance=args, schema=spec.input_schema)

        span = (
            self.traces.span(
                f"tool.{name}", "tools",
                tool_name=name, side_effect=spec.side_effect, risk=spec.risk,
            )
            if self.traces is not None
            else _NullSpan()
        )
        started = perf_counter()
        async with span:
            try:
                timeout = spec.timeout_ms / 1000
                if timeout > 0:
                    async with asyncio.timeout(timeout):
                        data = await self.registry.handler(name)(ctx, args)
                else:
                    data = await self.registry.handler(name)(ctx, args)
                # 步骤 4：输出 schema 是外部系统的契约；坏数据不能进入图状态。
                jsonschema.validate(
                    instance=data, schema=spec.output_schema
                )
                TOOL_CALLS.labels(tool=name, status="ok", code="OK").inc()
                return ToolResult(ok=True, data=data, trace_id=ctx.trace_id)
            except TimeoutError:
                return self._fail(
                    ctx, name, "TOOL_TIMEOUT",
                    f"tool timed out after {spec.timeout_ms}ms", True,
                )
            except jsonschema.ValidationError as exc:
                logger.warning(
                    "tool output schema mismatch: %s: %s", name, exc.message
                )
                return self._fail(
                    ctx, name, "TOOL_BAD_RESPONSE",
                    f"output does not match schema: {exc.message}", False,
                )
            except Exception as exc:
                logger.exception("tool failed: %s", name)
                # 适配器可提供稳定的上游错误码（UPSTREAM_TIMEOUT 等）；
                # 其他异常统一按可重试的工具不可用处理。
                code = getattr(exc, "code", "TOOL_UNAVAILABLE")
                retryable = bool(getattr(exc, "retryable", True))
                return self._fail(ctx, name, code, str(exc), retryable)
            finally:
                TOOL_DURATION.labels(tool=name).observe(
                    perf_counter() - started
                )

    @staticmethod
    def _fail(ctx: RequestContext, name: str, code: str, message: str,
              retryable: bool) -> ToolResult:
        TOOL_CALLS.labels(
            tool=name,
            status="forbidden" if code == "TOOL_FORBIDDEN" else "error",
            code=code,
        ).inc()
        return ToolResult(
            ok=False,
            trace_id=ctx.trace_id,
            error=ToolError(code=code, message=message, retryable=retryable),
        )
