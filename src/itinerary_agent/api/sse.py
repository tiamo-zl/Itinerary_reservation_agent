"""SSE 事件格式化。

事件结构由编排层产生，网关负责转成 sse-starlette 需要的 dict；
输出前统一脱敏，避免敏感字段直接返回给客户端。
"""

import json

from itinerary_agent.api.pii import scrub_obj
from itinerary_agent.domain.models import Event


def to_sse(event: Event) -> dict:
    return {
        "event": event.type,
        "data": json.dumps(scrub_obj(event.data), ensure_ascii=False),
    }
