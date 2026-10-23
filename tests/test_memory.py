from datetime import UTC, datetime

from itinerary_agent.domain.models import UserMemory
from itinerary_agent.infra.db import Database
from itinerary_agent.knowledge.memory import MemoryStore


async def test_memory_store_roundtrip(tmp_path):
    # 长期偏好落 SQLite，跨任务读取；这里只验证最小读写。
    db = Database(tmp_path / "m.db")
    await db.connect()
    store = MemoryStore(db)
    await store.upsert(UserMemory(
        memory_id="m1", tenant_id="demo-company", user_id="u001",
        kind="preference", key="hotel_chain", value="华住", confidence=0.9,
        updated_at=datetime.now(UTC),
    ))
    result = await store.get("demo-company", "u001", ["preference"])
    assert result[0].value == "华住"
    await db.close()
