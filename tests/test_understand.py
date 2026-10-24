from datetime import date

from itinerary_agent.orchestration.nodes.understand import normalize_payload


def test_normalize_model_aliases_and_duration():
    # 真实模型可能输出 destination/departure_date/budget 等别名。
    raw = {
        "destination": "北京",
        "departure_date": "2026-11-03",
        "duration_days": 2,
        "budget": 1000,
        "hotel_area": "王府井",
    }
    data = normalize_payload(raw, today=date(2026, 10, 21))
    assert data["destination_city"] == "北京"
    assert data["start_date"] == "2026-11-03"
    assert data["end_date"] == "2026-11-04"
    assert data["budget_limit"] == 1000
    assert data["need_flight"] is True
    assert data["need_hotel"] is True


def test_normalize_relative_weekday():
    data = normalize_payload(
        {"destination": "北京", "departure_date": "下周二", "duration_days": 2},
        today=date(2026, 10, 21),
    )
    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])
    assert start.weekday() == 1  # 周二
    assert start > date(2026, 10, 21)
    assert (end - start).days == 1
