"""确定性规则自动标注（silver labels）。

它只用于在没有人工标签时跑通链路、做冒烟对比，不能替代人工校准。
规则覆盖：状态、必需槽位、候选/选择一致性、预算、区域、舱位、
审批状态、摘要矛盾。
"""

from datetime import date

KNOWN_CITIES = (
    "北京", "上海", "广州", "深圳", "杭州", "成都", "南京",
    "武汉", "西安", "重庆", "苏州", "天津",
)

BOOKING_WORDS = ("已预订", "已选", "完成预订", "已确认", "已安排")
APPROVAL_WORDS = ("获批", "已批准", "审批通过", "已完成")


def _nights(request: dict) -> int:
    try:
        start = date.fromisoformat(request["start_date"])
        end = date.fromisoformat(request["end_date"])
    except (KeyError, TypeError, ValueError):
        return 1
    return max(1, (end - start).days)


def _flight_matches(selected: dict, option: dict) -> bool:
    return (
        selected.get("airline") == option.get("airline")
        and selected.get("price") == option.get("price")
        and selected.get("cabin") == option.get("cabin")
    )


def _hotel_matches(selected: dict, option: dict) -> bool:
    return (
        selected.get("hotel_name") == option.get("hotel_name")
        and selected.get("price_per_night") == option.get("price_per_night")
    )


def _summary_city(summary: str) -> str | None:
    for marker in ("安排", "前往", "去"):
        for city in KNOWN_CITIES:
            if f"{marker}{city}" in summary:
                return city
    return None


def auto_label(values: dict) -> dict:
    request = values.get("request") or {}
    options = values.get("options") or {}
    selected = values.get("selected") or {}
    policy = values.get("policy_result") or {}
    approval = values.get("approval") or {}
    summary = values.get("summary") or ""
    status = values.get("status") or "unknown"
    reasons: list[str] = []

    if status != "COMPLETED":
        reasons.append(f"status is {status}")
    for field, name in (
        ("destination_city", "destination"),
        ("start_date", "start date"),
        ("end_date", "end date"),
        ("budget_limit", "budget"),
    ):
        if request.get(field) in (None, ""):
            reasons.append(f"missing {name}")

    flights = options.get("flights") or []
    hotels = options.get("hotels") or []
    if request.get("need_flight") and not flights:
        reasons.append("need flight but no flight options")
    if request.get("need_hotel") and not hotels:
        reasons.append("need hotel but no hotel options")

    flight = selected.get("flight")
    hotel = selected.get("hotel")
    if not selected:
        reasons.append("no selection")
    if flight and not any(_flight_matches(flight, item) for item in flights):
        reasons.append("selected flight is not in options")
    if hotel and not any(_hotel_matches(hotel, item) for item in hotels):
        reasons.append("selected hotel is not in options")
    if request.get("need_hotel") and not hotel:
        reasons.append("need hotel but no hotel selected")

    approval_status = approval.get("status")
    if policy.get("passed") is False and approval_status != "approved":
        reasons.append("policy failed without approval")
    if policy.get("violations") and policy.get("passed") is True:
        reasons.append("policy passed despite violations")
    if policy.get("requires_approval") and approval_status != "approved":
        reasons.append("approval not approved")
    if (
        approval_status in {"rejected", "pending"}
        and any(word in summary for word in APPROVAL_WORDS)
    ):
        reasons.append("summary claims approval that is not granted")

    budget = request.get("budget_limit")
    if budget is not None:
        total = float(flight.get("price", 0) if flight else 0)
        if hotel:
            total += float(hotel.get("price_per_night", 0)) * _nights(request)
        if total > float(budget):
            reasons.append(f"total {total:.0f} exceeds budget {budget}")

    area = request.get("hotel_area")
    if area and hotel and area not in str(hotel.get("hotel_name", "")):
        reasons.append("hotel outside requested area")
    cabin = request.get("cabin")
    if (
        cabin and flight and flight.get("cabin") != cabin
        and (
            not policy.get("requires_approval")
            or approval_status != "approved"
        )
    ):
        reasons.append("cabin does not match request")

    if not summary.strip():
        reasons.append("empty summary")
    summary_city = _summary_city(summary)
    destination = request.get("destination_city")
    if summary_city and destination and summary_city != destination:
        reasons.append("summary destination mismatch")
    if (
        "往返" in summary
        and request.get("start_date") != request.get("end_date")
        and request.get("need_flight")
        and not flight
    ):
        reasons.append("summary claims round trip without selected flight")
    if (
        "往返" in summary
        and request.get("start_date") != request.get("end_date")
        and len(flights) < 2
    ):
        reasons.append("summary claims round trip but options do not cover it")

    if reasons:
        score = 2 if len(reasons) == 1 else 1
        return {"verdict": "fail", "score": score, "reasons": reasons}

    score = 5
    if policy.get("requires_approval") and approval_status == "approved":
        score = 4
    if request.get("start_date") == request.get("end_date"):
        score = min(score, 4)
    return {"verdict": "pass", "score": score, "reasons": []}
