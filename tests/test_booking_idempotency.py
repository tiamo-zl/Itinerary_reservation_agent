from itinerary_agent.adapters.mock.booking import MockBookingSystem
from tests.db_utils import open_test_db


async def test_booking_is_idempotent(tmp_path):
    # 同一个幂等键重复下单必须返回同一结果，不能重复扣款/出票。
    db = await open_test_db()
    booking = MockBookingSystem(db)
    first = await booking.book("book_flight", "t1:1:1", {"option_id": "f1"})
    second = await booking.book("book_flight", "t1:1:1", {"option_id": "f1"})
    assert first["booking_id"] == second["booking_id"]
    assert first["replayed"] is False
    assert second["replayed"] is True
    await db.close()
