"""游标分页。

游标是 base64url(JSON) 的不透明值，只暴露给客户端原样回传；
服务端用排序键（时间 + 唯一 ID）做 keyset 查询，避免 LIMIT/OFFSET
在数据量大时扫描前面所有行。
"""

import base64
import binascii
import json
from datetime import datetime

from itinerary_agent.application.errors import BadRequest

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def normalize_limit(limit: int, default: int = DEFAULT_LIMIT) -> int:
    """把用户输入收敛到 [1, MAX_LIMIT]；非法值按默认上限处理。"""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, MAX_LIMIT))


def encode_cursor(values: dict) -> str:
    payload = json.dumps(
        values, ensure_ascii=False, separators=(",", ":"), default=str
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict | None:
    """解析客户端回传的游标；损坏的游标返回 400，不猜测偏移量。"""
    if not cursor:
        return None
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        values = json.loads(raw)
    except (ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise BadRequest("invalid cursor") from exc
    if not isinstance(values, dict):
        raise BadRequest("invalid cursor")
    return values


def datetime_value(cursor: dict, key: str) -> datetime | None:
    value = cursor.get(key)
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise BadRequest("invalid cursor") from exc


def build_page(items: list[dict], limit: int,
               key) -> tuple[list[dict], str | None]:
    """多取一条判断是否还有下一页，并用最后一条的排序键生成游标。"""
    if len(items) <= limit:
        return items, None
    page = items[:limit]
    return page, encode_cursor(key(page[-1]))
