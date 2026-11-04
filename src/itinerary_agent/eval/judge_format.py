"""把 judge 输入格式化成人工可读的终端摘要。"""

import json


def _brief(items: list, limit: int = 3) -> str:
    shown = items[:limit]
    suffix = f" (+{len(items) - limit} more)" if len(items) > limit else ""
    return json.dumps(shown, ensure_ascii=False) + suffix


def format_context(context: dict) -> str:
    """压缩 request/selected/options/policy/summary，避免一次刷屏。"""
    policy = context.get("policy") or {}
    approval = context.get("approval") or {}
    options = context.get("options") or {}
    flights = options.get("flights") or []
    hotels = options.get("hotels") or []
    return "\n".join([
        "request   : " + json.dumps(
            context.get("request") or {}, ensure_ascii=False
        ),
        "selected  : " + json.dumps(
            context.get("selected") or {}, ensure_ascii=False
        ),
        f"flights   : {len(flights)} {_brief(flights)}",
        f"hotels    : {len(hotels)} {_brief(hotels)}",
        "policy    : "
        + json.dumps(
            {
                "passed": policy.get("passed"),
                "requires_approval": policy.get("requires_approval"),
                "violations": policy.get("violations") or [],
            },
            ensure_ascii=False,
        ),
        "approval  : " + json.dumps(approval, ensure_ascii=False),
        "summary   : " + (context.get("summary") or "<empty>"),
    ])
