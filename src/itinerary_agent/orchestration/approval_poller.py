"""审批结果轮询器。

demo 没有企业审批回调，因此用轻量轮询：发现 WAITING_APPROVAL 的任务
已有结果，就调用编排服务从 Checkpoint 恢复。
"""

import asyncio

from itinerary_agent.domain.models import ApprovalStatus, Decision, RequestContext


class ApprovalPoller:
    def __init__(self, db, approvals, orchestrator, interval: float = 2.0):
        self.db = db
        self.approvals = approvals
        self.orchestrator = orchestrator
        self.interval = interval
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def run(self) -> None:
        """轮询审批结果并恢复任务。

        步骤：
        1. 定时查询等待审批且已有结果的任务；
        2. 恢复前把任务从 WAITING_APPROVAL 推进到 EXECUTING；
        3. 用任务 trace/tenant/user 构造恢复上下文；
        4. 调用编排服务从 Checkpoint 恢复；
        5. 恢复失败时回滚到 WAITING_APPROVAL，等待下一轮重试。
        """
        while True:
            await asyncio.sleep(self.interval)

            # 步骤 1：只处理“任务仍在等待 + 审批已有结论”的组合。
            rows = await self.db.fetchall(
                "SELECT a.approval_id, a.task_id, a.status, t.tenant_id, "
                "t.user_id, t.trace_id "
                "FROM approvals a JOIN tasks t ON t.task_id = a.task_id "
                "WHERE t.status = 'WAITING_APPROVAL' "
                "AND a.status IN ('approved', 'rejected')"
            )

            for row in rows:
                # 步骤 2：先改状态，避免下一轮重复恢复同一任务。
                await self.db.execute(
                    "UPDATE tasks SET status = 'EXECUTING' WHERE task_id = ?",
                    (row["task_id"],),
                )

                # 步骤 3：恢复上下文必须复用任务 trace，不能另起 trace。
                ctx = RequestContext(
                    trace_id=row["trace_id"] or f"approval-{row['task_id']}",
                    tenant_id=row["tenant_id"],
                    user_id=row["user_id"],
                    session_id="approval",
                )
                decision = Decision(
                    action="continue",
                    approval_status=ApprovalStatus(row["status"]),
                )

                # 步骤 4：从 Checkpoint 恢复图，事件在这里无需再转发给前端。
                try:
                    async for _ in self.orchestrator.resume(
                        ctx, row["task_id"], decision
                    ):
                        pass
                except Exception:  # noqa: BLE001 - 恢复失败时回滚状态等待重试
                    # 步骤 5：失败回滚，避免任务卡在 EXECUTING。
                    await self.db.execute(
                        "UPDATE tasks SET status = 'WAITING_APPROVAL' "
                        "WHERE task_id = ?",
                        (row["task_id"],),
                    )
