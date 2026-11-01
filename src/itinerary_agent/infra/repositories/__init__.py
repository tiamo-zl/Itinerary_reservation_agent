"""PostgreSQL 仓储实现。

约束：
- 只有这一层可以写 SQL、认识表名和列名；
- 返回普通 dict/DTO，不把驱动行对象泄漏到应用层；
- 不做权限判断，租户/角色/归属校验属于 application。
"""

from itinerary_agent.infra.repositories.approval_repository import (
    PostgresApprovalRepository,
)
from itinerary_agent.infra.repositories.conversation_repository import (
    PostgresConversationRepository,
)
from itinerary_agent.infra.repositories.feedback_repository import (
    PostgresFeedbackRepository,
)
from itinerary_agent.infra.repositories.outbox_repository import (
    PostgresOutboxRepository,
)
from itinerary_agent.infra.repositories.task_repository import PostgresTaskRepository
from itinerary_agent.infra.repositories.trace_repository import PostgresTraceRepository

__all__ = [
    "PostgresApprovalRepository",
    "PostgresConversationRepository",
    "PostgresFeedbackRepository",
    "PostgresOutboxRepository",
    "PostgresTaskRepository",
    "PostgresTraceRepository",
]
