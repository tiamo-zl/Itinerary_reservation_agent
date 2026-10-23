"""模拟机票/酒店库存。

返回结构化候选，不负责差标判断；价格是否合规由 control 层计算。
"""

from itinerary_agent.domain.models import FlightOption, HotelOption


class MockFlightInventory:
    async def search(self, origin: str, destination: str, date: str) -> list[FlightOption]:
        return [
            FlightOption(
                option_id="f1", airline="国航", flight_no="CA1501",
                origin=origin, destination=destination,
                depart_at=f"{date}T08:00", arrive_at=f"{date}T10:10",
                cabin="economy", price=1280.0, refundable=True, seats_left=9,
            ),
            FlightOption(
                option_id="f2", airline="东航", flight_no="MU5101",
                origin=origin, destination=destination,
                depart_at=f"{date}T12:00", arrive_at=f"{date}T14:05",
                cabin="economy", price=980.0, refundable=False, seats_left=4,
            ),
        ]


class MockHotelInventory:
    async def search(self, city: str, check_in: str, check_out: str,
                     area: str | None) -> list[HotelOption]:
        return [
            HotelOption(
                option_id="h1", hotel_name="王府井酒店", city=city,
                area=area or "王府井", room_type="大床房",
                price_per_night=480.0, refundable=True, distance_to_center_km=1.2,
            ),
            HotelOption(
                option_id="h2", hotel_name="国贸大酒店", city=city,
                area=area or "国贸", room_type="标准间",
                price_per_night=720.0, refundable=True, distance_to_center_km=4.5,
            ),
        ]
