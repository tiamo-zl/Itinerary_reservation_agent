"""pytest 全局夹具：PostgreSQL 迁移与用例隔离。"""

import os

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from psycopg import AsyncConnection

from tests.db_utils import TEST_DATABASE_URL

# 只清理业务表；LangGraph checkpoint 表由库自己管理，按 thread_id 隔离。
APP_TABLES = (
    "tasks",
    "messages",
    "user_memories",
    "audit_log",
    "spans",
    "llm_cache",
    "embedding_cache",
    "llm_calls",
    "approvals",
    "idempotency",
    "badcases",
    "outbox",
    "policy_clauses",
    "policy_edges",
    "policy_tables",
    "policy_definitions",
    "policy_ingest_reviews",
)


@pytest.fixture(scope="session", autouse=True)
def migrate_database():
    """整个测试会话只跑一次 Alembic。"""
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest_asyncio.fixture(autouse=True)
async def clean_database(migrate_database):
    """每条用例前清空业务表，避免测试之间互相污染。"""
    conn = await AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                f"TRUNCATE {', '.join(APP_TABLES)} RESTART IDENTITY CASCADE"
            )
    finally:
        await conn.close()
    yield
