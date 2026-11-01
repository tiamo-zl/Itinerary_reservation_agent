"""任务恢复租约：并发恢复只能有一个赢家。"""

import asyncio

from itinerary_agent.infra.repositories.task_repository import (
    PostgresTaskRepository,
)
from tests.db_utils import open_test_db


async def _insert_task(db, task_id: str, status: str = "WAITING_APPROVAL"):
    await db.execute(
        "INSERT INTO tasks (task_id, tenant_id, user_id, status, revision, "
        "updated_at) VALUES (?, ?, ?, ?, ?, now())",
        (task_id, "demo-company", "u001", status, 0),
    )


async def test_resume_lease_is_exclusive(tmp_path):
    db = await open_test_db()
    repo = PostgresTaskRepository(db)
    await _insert_task(db, "t1")

    first, second = await asyncio.gather(
        repo.acquire_resume_lease("t1", "owner-a", 60),
        repo.acquire_resume_lease("t1", "owner-b", 60),
    )
    assert (first is None) != (second is None)
    winner = first or second
    assert winner["version"] == 1

    owner = "owner-a" if first else "owner-b"
    await repo.release_lease("t1", owner)
    again = await repo.acquire_resume_lease("t1", "owner-b", 60)
    assert again is not None
    await db.close()


async def test_terminal_task_cannot_be_resumed(tmp_path):
    db = await open_test_db()
    repo = PostgresTaskRepository(db)
    await _insert_task(db, "done", status="COMPLETED")

    assert await repo.acquire_resume_lease("done", "owner-a", 60) is None
    await db.close()
