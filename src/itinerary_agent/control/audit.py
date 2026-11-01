"""审计端口。

控制层只依赖这个协议；SQL 实现在 infra/repositories/audit_repository.py。
"""

from typing import Protocol


class AuditLog(Protocol):
    async def record(self, trace_id: str, task_id: str | None, actor: str,
                     action: str, inputs: dict, rule_ids: list[str],
                     policy_version: str, decision: str,
                     reason: str) -> None: ...
