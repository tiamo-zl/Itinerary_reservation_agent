"""HTTP 机票/酒店库存适配器。"""

from itinerary_agent.adapters.http.client import JsonHttpClient
from itinerary_agent.domain.models import FlightOption, HotelOption


class HttpFlightInventory:
    def __init__(self, client: JsonHttpClient):
        self.client = client

    async def search(self, origin: str, destination: str,
                     date: str) -> list[FlightOption]:
        data = await self.client.get(
            "/inventory/flights",
            params={"origin": origin, "destination": destination, "date": date},
        )
        return [FlightOption.model_validate(item) for item in data["flights"]]


class HttpHotelInventory:
    def __init__(self, client: JsonHttpClient):
        self.client = client

    async def search(self, city: str, check_in: str, check_out: str,
                     area: str | None) -> list[HotelOption]:
        params = {"city": city, "check_in": check_in, "check_out": check_out}
        if area:
            params["area"] = area
        data = await self.client.get("/inventory/hotels", params=params)
        return [HotelOption.model_validate(item) for item in data["hotels"]]
