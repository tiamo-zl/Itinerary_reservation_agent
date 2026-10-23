"""编排层对外事件。

Event 的数据结构定义在 domain，避免 api 和 orchestration 各有一套。
"""

from itinerary_agent.domain.models import Event

__all__ = ["Event"]
