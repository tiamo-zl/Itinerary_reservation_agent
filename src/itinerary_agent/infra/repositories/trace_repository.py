"""Trace/span 与线上概览的 PostgreSQL 仓储。

七层纵向视图不是另一套存储：按 trace_id 取出 span，上层再按
parent_span_id 还原调用树。概览聚合直接查 PostgreSQL，demo 足够；
生产应换成 Prometheus/ClickHouse 等时序或分析存储。
"""

from itinerary_agent.infra.db import Database


class PostgresTraceRepository:
    def __init__(self, db: Database):
        self.db = db

    async def load_spans(self, trace_id: str) -> list[dict]:
        """读取一条 trace 的全部 span；jsonb 由 psycopg 直接转成 dict。"""
        rows = await self.db.fetchall(
            "SELECT span_id, parent_span_id, name, layer, status, "
            "start_time, duration_ms, attributes FROM spans "
            "WHERE trace_id = ? ORDER BY start_time",
            (trace_id,),
        )
        result = []
        for row in rows:
            item = dict(row)
            attributes = item.get("attributes") or {}
            if isinstance(attributes, str):
                import json

                attributes = json.loads(attributes)
            item["attributes"] = attributes
            result.append(item)
        return result

    async def load_flow_spans(self, trace_id: str) -> list[dict]:
        """只取编排层节点 span，用于构造流转图。"""
        rows = await self.db.fetchall(
            "SELECT name, status, start_time FROM spans "
            "WHERE trace_id = ? AND layer = 'orchestration' "
            "ORDER BY start_time",
            (trace_id,),
        )
        return [dict(row) for row in rows]

    async def list_traces(self, limit: int = 50,
                          tenant_id: str | None = None) -> list[dict]:
        """最近的 trace 汇总；tenant_id 为空表示管理员/控制台全量视图。"""
        where = ""
        params: list = []
        if tenant_id is not None:
            # 没有关联任务的 trace（后台/检索）不携带租户信息，保留可见。
            where = "WHERE (t.tenant_id = ? OR t.tenant_id IS NULL)"
            params.append(tenant_id)
        rows = await self.db.fetchall(
            "SELECT s.trace_id, MIN(s.start_time) AS started_at, "
            "COUNT(*) AS span_count, "
            "SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS error_count, "
            "MAX(s.duration_ms) AS max_duration_ms, "
            "string_agg(DISTINCT s.layer, ',') AS layers, "
            "MAX(t.task_id) AS task_id, MAX(t.status) AS task_status, "
            "MAX(t.tenant_id) AS tenant_id "
            "FROM spans s LEFT JOIN tasks t ON t.trace_id = s.trace_id "
            f"{where} GROUP BY s.trace_id ORDER BY started_at DESC LIMIT ?",
            (*params, limit),
        )
        traces = []
        for row in rows:
            item = dict(row)
            item["layers"] = sorted((item["layers"] or "").split(","))
            traces.append(item)
        return traces

    async def list_task_summaries(self, limit: int = 50,
                                  tenant_id: str | None = None) -> list[dict]:
        """按 task 聚合 trace，供概览页先选 task 再查看 trace。"""
        where = ""
        params: list = []
        if tenant_id is not None:
            where = "WHERE t.tenant_id = ?"
            params.append(tenant_id)
        rows = await self.db.fetchall(
            "SELECT t.task_id, t.user_id, t.tenant_id, t.status, t.revision, "
            "t.trace_id, t.updated_at, "
            "(SELECT COUNT(DISTINCT s.trace_id) FROM spans s "
            " WHERE s.trace_id = t.trace_id "
            " OR s.attributes->>'task_id' = t.task_id) AS trace_count, "
            "(SELECT COUNT(*) FROM spans s "
            " WHERE s.trace_id = t.trace_id "
            " OR s.attributes->>'task_id' = t.task_id) AS span_count, "
            "(SELECT MAX(s.start_time) FROM spans s "
            " WHERE s.trace_id = t.trace_id "
            " OR s.attributes->>'task_id' = t.task_id) AS last_span_at "
            f"FROM tasks t {where} ORDER BY t.updated_at DESC LIMIT ?",
            (*params, limit),
        )
        return [dict(row) for row in rows]

    async def list_traces_for_task(self, task_id: str) -> list[dict]:
        """返回某任务关联的全部 trace。

        兼容旧数据：优先用 tasks.trace_id，同时合并 span 里的 task_id。
        """
        rows = await self.db.fetchall(
            "SELECT s.trace_id, MIN(s.start_time) AS started_at, "
            "COUNT(*) AS span_count, "
            "SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS error_count, "
            "MAX(s.duration_ms) AS max_duration_ms, "
            "string_agg(DISTINCT s.layer, ',') AS layers "
            "FROM spans s "
            "WHERE s.trace_id = COALESCE("
            "  (SELECT trace_id FROM tasks WHERE task_id = ?), ''"
            ") OR s.attributes->>'task_id' = ? "
            "GROUP BY s.trace_id ORDER BY started_at",
            (task_id, task_id),
        )
        result = []
        for row in rows:
            item = dict(row)
            item["layers"] = sorted((item["layers"] or "").split(","))
            result.append(item)
        return result

    async def overview_snapshot(self) -> dict:
        """一次性取出概览所需的原始聚合，不在这里算业务指标。"""
        totals = dict(await self.db.fetchone(
            "SELECT COUNT(DISTINCT trace_id) AS traces, COUNT(*) AS spans, "
            "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors, "
            "AVG(duration_ms) AS avg_duration_ms FROM spans"
        ))
        durations = [
            row["duration_ms"]
            for row in await self.db.fetchall("SELECT duration_ms FROM spans")
        ]
        layers = [
            dict(row)
            for row in await self.db.fetchall(
                "SELECT layer, COUNT(*) AS spans, "
                "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors, "
                "AVG(duration_ms) AS avg_duration_ms "
                "FROM spans GROUP BY layer ORDER BY layer"
            )
        ]
        llm = dict(await self.db.fetchone(
            "SELECT COUNT(*) AS calls, "
            "COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
            "COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
            "COALESCE(SUM(cost_usd), 0) AS cost_usd FROM llm_calls"
        ))
        return {
            "totals": totals,
            "durations": durations,
            "layers": layers,
            "llm": llm,
            "approvals": await self._status_counts("approvals"),
            "task_status": await self._status_counts("tasks"),
            "badcases": await self._status_counts("badcases"),
        }

    async def _status_counts(self, table: str) -> list[dict]:
        """按 status 分组计数；table 只接受内部白名单。"""
        if table not in {"approvals", "tasks", "badcases"}:
            raise ValueError(f"unsupported table: {table}")
        rows = await self.db.fetchall(
            f"SELECT status, COUNT(*) AS count FROM {table} GROUP BY status"
        )
        return [dict(row) for row in rows]
