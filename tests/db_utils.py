"""测试数据库工具。

所有测试共享一个 PostgreSQL 测试库；conftest 在每条用例前清空业务表。
"""

import os

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://itinerary:itinerary_dev@127.0.0.1:55432/itinerary_test",
)


def make_test_settings(**overrides) -> Settings:
    """构造指向测试库的配置，默认离线脚本模型。"""
    values = {
        "_env_file": None,
        "environment": "test",
        "database_url": TEST_DATABASE_URL,
        "model_mode": "scripted",
        "adapter_mode": "mock",
        "mock_approval_delay_seconds": 999,
    }
    values.update(overrides)
    return Settings(**values)


async def open_test_db() -> Database:
    db = Database(TEST_DATABASE_URL)
    await db.connect()
    return db
