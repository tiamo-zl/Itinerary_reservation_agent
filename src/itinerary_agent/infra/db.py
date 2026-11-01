"""兼容入口：Database 已迁移到 PostgreSQL 实现。

保留 `infra.db` 这个导入路径，避免一次性修改所有历史导入；
新代码请直接从 `itinerary_agent.infra.database` 导入。
"""

from itinerary_agent.infra.database import Database

__all__ = ["Database"]
