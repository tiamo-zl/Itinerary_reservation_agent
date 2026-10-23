"""工具注册表。

注册表只存 ToolSpec + 处理函数；权限、风险判断由编排层调用 control.guard，
工具层本身保持“执行器”角色，不反向依赖控制层。
"""

from collections.abc import Awaitable, Callable

from itinerary_agent.domain.models import ToolSpec

ToolHandler = Callable[[object, dict], Awaitable[dict]]


class ToolRegistry:
    def __init__(self):
        self._handlers: dict[str, tuple[ToolSpec, ToolHandler]] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        # 同名工具重复注册通常是装配错误，直接失败而不是覆盖。
        if spec.name in self._handlers:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._handlers[spec.name] = (spec, handler)

    def spec(self, name: str) -> ToolSpec:
        return self._handlers[name][0]

    def handler(self, name: str) -> ToolHandler:
        return self._handlers[name][1]

    def names(self) -> list[str]:
        return sorted(self._handlers)
