from tests.db_utils import open_test_db


async def test_init_and_insert_task(tmp_path):
    # 使用共享 PostgreSQL 测试库，conftest 会在用例前清空业务表。
    db = await open_test_db()
    await db.execute(
        "INSERT INTO tasks (task_id, tenant_id, user_id, status, revision, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("t1", "demo-company", "u001", "PLANNING", 0, "2026-10-21T00:00:00+00:00"),
    )
    row = await db.fetchone("SELECT status FROM tasks WHERE task_id = ?", ("t1",))
    assert row["status"] == "PLANNING"
    await db.close()
