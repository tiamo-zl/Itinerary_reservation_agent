"""SQLite 结构化存储。

职责边界：
- tasks 保存任务索引（状态机的最小投影），完整状态仍在 LangGraph Checkpoint；
- messages/user_memories 属于知识与记忆层；
- audit_log/approvals/idempotency 属于控制与工具层；
- spans/llm_cache/llm_calls 属于可观测与模型网关。

所有访问都是 async，避免阻塞 FastAPI 事件循环。
"""

from pathlib import Path

import aiosqlite

SCHEMA = """
-- 任务索引：用于 /tasks 查询、审批轮询，不替代 Checkpoint。
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  status TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  trace_id TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  task_id TEXT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_memories (
  memory_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence REAL NOT NULL,
  source_task_id TEXT,
  updated_at TEXT NOT NULL,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  decision_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  inputs_hash TEXT NOT NULL,
  rule_ids TEXT NOT NULL,
  policy_version TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL
);
-- 全链路 span：按 trace_id 查询后按 parent_span_id 建树。
CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  parent_span_id TEXT,
  name TEXT NOT NULL,
  layer TEXT NOT NULL,
  status TEXT NOT NULL,
  start_time TEXT NOT NULL,
  duration_ms REAL NOT NULL,
  attributes TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embedding_cache (
  cache_key TEXT PRIMARY KEY,
  vector TEXT NOT NULL,
  created_at TEXT NOT NULL
);
-- 模型调用账本：按 task/tenant/purpose 聚合成本与 token。
CREATE TABLE IF NOT EXISTS llm_calls (
  call_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  tenant_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  duration_ms REAL NOT NULL,
  created_at TEXT NOT NULL
);
-- 审批单：task_id + revision 唯一标识一次审批，避免修改后复用旧审批。
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL,
  comment TEXT,
  payload TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
-- 写操作幂等表：预订/审批重试时直接返回既有结果。
CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  result TEXT NOT NULL,
  created_at TEXT NOT NULL
);
-- Badcase 回流：trace/task 关联 + 期望/实际 + 处理状态。
CREATE TABLE IF NOT EXISTS badcases (
  badcase_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  tenant_id TEXT NOT NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  user_input TEXT NOT NULL DEFAULT '',
  expected TEXT NOT NULL DEFAULT '',
  actual TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  root_cause TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_badcases_status ON badcases(status);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """建立连接并确保 schema 存在。

        使用 IF NOT EXISTS，可重复执行；不会删除已有数据。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        # Row 工厂让查询结果可以按列名访问，避免依赖列顺序。
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._conn.commit()

    async def _migrate(self) -> None:
        """给已有 SQLite 文件补新增列；只做 additive migration。"""
        async with self.conn.execute("PRAGMA table_info(tasks)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "trace_id" not in columns:
            await self.conn.execute("ALTER TABLE tasks ADD COLUMN trace_id TEXT")

        async with self.conn.execute("PRAGMA table_info(approvals)") as cursor:
            approval_columns = {row["name"] for row in await cursor.fetchall()}
        if "payload" not in approval_columns:
            await self.conn.execute("ALTER TABLE approvals ADD COLUMN payload TEXT")

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database not connected")
        return self._conn

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """执行写语句并立即提交；demo 规模不需要显式事务管理。"""
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def fetchone(self, sql: str, params: tuple = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cur:
            return list(await cur.fetchall())

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            # 置空以便测试或重启时能重新 connect。
            self._conn = None
