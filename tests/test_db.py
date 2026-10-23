from itinerary_agent.infra.db import Database


async def test_init_and_insert_task(tmp_path):
    db = Database(tmp_path / "test.db")
    await db.connect()
    await db.execute(
        "INSERT INTO tasks (task_id, tenant_id, user_id, status, revision, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("t1", "demo-company", "u001", "PLANNING", 0, "2026-10-21T00:00:00+00:00"),
    )
    row = await db.fetchone("SELECT status FROM tasks WHERE task_id = ?", ("t1",))
    assert row["status"] == "PLANNING"
    await db.close()
