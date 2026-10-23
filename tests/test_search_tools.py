from itinerary_agent.adapters.mock.inventory import MockFlightInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory


async def test_mock_search_returns_options():
    flights = MockFlightInventory()
    results = await flights.search(origin="上海", destination="北京", date="2026-11-03")
    assert results
    assert results[0].destination == "北京"

    users = MockUserDirectory()
    profile = await users.get("u001")
    assert profile.employee_level == "L2"
