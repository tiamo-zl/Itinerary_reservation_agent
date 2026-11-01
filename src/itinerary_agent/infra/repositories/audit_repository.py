"""审计日志仓储。

inputs 只存哈希，避免把完整敏感参数写入审计表。
"""

import hashlib
import json
from uuid import uuid4

from itinerary_agent.infra.db import Database


class PostgresAuditLog:
    def __init__(self, db: Database):
        self.db = db

    async def record(self, trace_id: str, task_id: str | None, actor: str,
                     action: str, inputs: dict, rule_ids: list[str],
                     policy_version: str, decision: str, reason: str) -> None:
        await self.db.execute(
            "INSERT INTO audit_log (decision_id, trace_id, task_id, actor, action, "
            "inputs_hash, rule_ids, policy_version, decision, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())",
            (
                uuid4().hex, trace_id, task_id, actor, action,
                hashlib.sha256(
                    json.dumps(
                        inputs, sort_keys=True, ensure_ascii=False
                    ).encode()
                ).hexdigest(),
                json.dumps(rule_ids), policy_version, decision, reason,
            ),
        )
