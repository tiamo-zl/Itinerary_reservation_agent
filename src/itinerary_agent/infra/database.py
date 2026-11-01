"""PostgreSQL 访问层。

职责边界：
- 统一连接池、占位符转换和行工厂；
- `transaction()` 是唯一显式事务边界；
- 仓储只依赖这个对象，不直接创建连接。

历史代码使用 `?` 占位符；这里统一转换为 psycopg 的 `%s`，
避免一次性改动所有 SQL。新代码可以直接写 `%s`。
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

# 只替换独立的 `?` 占位符；PostgreSQL 的 jsonb `?` 操作符暂未使用。
_PLACEHOLDER = re.compile(r"\?")

# 事务上下文：同一 asyncio task 内的多次 execute/fetch 共用一个连接。
_current_conn: ContextVar[AsyncConnection | None] = ContextVar(
    "current_conn", default=None
)


class Database:
    """异步 PostgreSQL 连接池。

    - 连接使用 autocommit，单条语句立即生效；
    - 需要原子性时使用 `async with db.transaction():`；
    - 所有行以 dict 返回，避免上层依赖列顺序。
    """

    def __init__(self, url: str, min_size: int = 1, max_size: int = 10):
        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        """打开连接池并等待至少一个连接可用。"""
        if self._pool is not None:
            return
        self._pool = AsyncConnectionPool(
            conninfo=self.url,
            min_size=self.min_size,
            max_size=self.max_size,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        await self._pool.open()
        await self._pool.wait()

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("database not connected")
        return self._pool

    @staticmethod
    def _sql(sql: str) -> str:
        """把历史 `?` 占位符转成 psycopg 的 `%s`。"""
        return _PLACEHOLDER.sub("%s", sql)

    @asynccontextmanager
    async def _connection(self) -> AsyncIterator[AsyncConnection]:
        """优先复用当前事务连接，否则从池里借一个。"""
        current = _current_conn.get()
        if current is not None:
            yield current
            return
        async with self.pool.connection() as conn:
            yield conn

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """执行写语句；单条语句自动提交，事务内则加入当前事务。"""
        async with self._connection() as conn, conn.cursor() as cur:
            await cur.execute(self._sql(sql), params)
            return cur.rowcount

    async def fetchone(self, sql: str,
                       params: Sequence[Any] = ()) -> dict | None:
        async with (
            self._connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(self._sql(sql), params)
            return await cur.fetchone()

    async def fetchall(self, sql: str,
                       params: Sequence[Any] = ()) -> list[dict]:
        async with (
            self._connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(self._sql(sql), params)
            return list(await cur.fetchall())

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """显式事务边界；异常时回滚。"""
        async with self.pool.connection() as conn:
            token = _current_conn.set(conn)
            try:
                async with conn.transaction():
                    yield conn
            finally:
                _current_conn.reset(token)

    async def ping(self) -> bool:
        """就绪探针使用；失败返回 False，不抛异常。"""
        try:
            row = await self.fetchone("SELECT 1 AS ok")
            return bool(row and row["ok"] == 1)
        except Exception:  # noqa: BLE001 - 探针只关心可用性
            return False

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
