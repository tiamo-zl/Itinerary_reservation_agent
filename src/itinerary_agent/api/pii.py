"""兼容入口：脱敏实现已移动到 security.pii。"""

from itinerary_agent.security.pii import scrub, scrub_obj

__all__ = ["scrub", "scrub_obj"]
