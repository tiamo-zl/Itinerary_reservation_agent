"""工具层对外契约。

实际模型定义在 domain，避免工具层和编排层各维护一套 schema。
这里集中 re-export，方便工具实现只 import 一个模块。
"""

from itinerary_agent.domain.models import ToolError, ToolResult, ToolSpec

__all__ = ["ToolError", "ToolResult", "ToolSpec"]
