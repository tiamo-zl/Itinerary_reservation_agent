"""Trace 查询、树形重建与线上概览。

七层纵向视图不是另一套存储：按 trace_id 取出 span，再按 parent_span_id
还原调用树即可。概览页直接对 SQLite 做聚合，demo 足够；生产应换成
Prometheus/ClickHouse 等时序或分析存储。
"""

import json

from itinerary_agent.infra.db import Database


async def load_trace_tree(db: Database, trace_id: str) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time", (trace_id,)
    )
    nodes: dict[str, dict] = {}
    roots: list[dict] = []

    for row in rows:
        nodes[row["span_id"]] = {
            "span_id": row["span_id"],
            "parent_span_id": row["parent_span_id"],
            "name": row["name"],
            "layer": row["layer"],
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "attributes": json.loads(row["attributes"]),
            "children": [],
        }

    for node in nodes.values():
        parent = nodes.get(node["parent_span_id"])
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


async def list_task_summaries(db: Database, limit: int = 50) -> list[dict]:
    """按 task 聚合 trace，供概览页先选 task 再查看 trace。"""
    rows = await db.fetchall(
        "SELECT t.task_id, t.user_id, t.tenant_id, t.status, t.revision, "
        "t.trace_id, t.updated_at, "
        "(SELECT COUNT(DISTINCT s.trace_id) FROM spans s "
        " WHERE s.trace_id = t.trace_id "
        " OR json_extract(s.attributes, '$.task_id') = t.task_id) AS trace_count, "
        "(SELECT COUNT(*) FROM spans s "
        " WHERE s.trace_id = t.trace_id "
        " OR json_extract(s.attributes, '$.task_id') = t.task_id) AS span_count, "
        "(SELECT MAX(s.start_time) FROM spans s "
        " WHERE s.trace_id = t.trace_id "
        " OR json_extract(s.attributes, '$.task_id') = t.task_id) AS last_span_at "
        "FROM tasks t ORDER BY t.updated_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in rows]


async def list_traces_for_task(db: Database, task_id: str) -> list[dict]:
    """返回某任务关联的全部 trace。

    兼容旧数据：优先用 tasks.trace_id，同时合并 Span 属性中的 task_id。
    """
    rows = await db.fetchall(
        "SELECT s.trace_id, MIN(s.start_time) AS started_at, "
        "COUNT(*) AS span_count, "
        "SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS error_count, "
        "MAX(s.duration_ms) AS max_duration_ms, "
        "GROUP_CONCAT(DISTINCT s.layer) AS layers "
        "FROM spans s "
        "WHERE s.trace_id = COALESCE("
        "  (SELECT trace_id FROM tasks WHERE task_id = ?), ''"
        ") OR json_extract(s.attributes, '$.task_id') = ? "
        "GROUP BY s.trace_id ORDER BY started_at",
        (task_id, task_id),
    )
    result = []
    for row in rows:
        item = dict(row)
        item["layers"] = sorted((item["layers"] or "").split(","))
        result.append(item)
    return result


async def list_traces(db: Database, limit: int = 50) -> list[dict]:
    """列出最近的 trace，供回放页和概览页使用。"""
    rows = await db.fetchall(
        "SELECT s.trace_id, MIN(s.start_time) AS started_at, "
        "COUNT(*) AS span_count, "
        "SUM(CASE WHEN s.status = 'error' THEN 1 ELSE 0 END) AS error_count, "
        "MAX(s.duration_ms) AS max_duration_ms, "
        "GROUP_CONCAT(DISTINCT s.layer) AS layers, "
        "MAX(t.task_id) AS task_id, MAX(t.status) AS task_status, "
        "MAX(t.tenant_id) AS tenant_id "
        "FROM spans s LEFT JOIN tasks t ON t.trace_id = s.trace_id "
        "GROUP BY s.trace_id ORDER BY started_at DESC LIMIT ?",
        (limit,),
    )
    traces = []
    for row in rows:
        item = dict(row)
        item["layers"] = sorted((item["layers"] or "").split(","))
        traces.append(item)
    return traces


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, int(len(values) * ratio))
    return values[index]


async def trace_overview(db: Database) -> dict:
    """线上概览：请求、延迟、错误、模型成本、审批和 badcase。

    步骤：
    1. 汇总 trace/span 总量、错误率和 P95；
    2. 按 layer 聚合延迟；
    3. 汇总模型调用 token/成本；
    4. 汇总审批、任务、badcase 状态；
    5. 附带最近 trace 方便跳转。
    """
    # 步骤 1：全局 totals 与 P95。
    totals_row = await db.fetchone(
        "SELECT COUNT(DISTINCT trace_id) AS traces, COUNT(*) AS spans, "
        "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors, "
        "AVG(duration_ms) AS avg_duration_ms FROM spans"
    )
    durations = [
        row["duration_ms"]
        for row in await db.fetchall("SELECT duration_ms FROM spans")
    ]
    totals = dict(totals_row)
    totals["error_rate"] = (
        (totals["errors"] or 0) / totals["spans"] if totals["spans"] else 0.0
    )
    totals["p95_duration_ms"] = _percentile(durations, 0.95)

    # 步骤 2：按层聚合 span 数量和平均延迟。
    layers = [
        dict(row)
        for row in await db.fetchall(
            "SELECT layer, COUNT(*) AS spans, "
            "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors, "
            "AVG(duration_ms) AS avg_duration_ms "
            "FROM spans GROUP BY layer ORDER BY layer"
        )
    ]

    # 步骤 3：模型调用账本聚合。
    llm = dict(await db.fetchone(
        "SELECT COUNT(*) AS calls, "
        "COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
        "COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
        "COALESCE(SUM(cost_usd), 0) AS cost_usd FROM llm_calls"
    ))
    # 步骤 4：审批、任务、badcase 状态分布。
    approvals = [
        dict(row)
        for row in await db.fetchall(
            "SELECT status, COUNT(*) AS count FROM approvals GROUP BY status"
        )
    ]
    task_status = [
        dict(row)
        for row in await db.fetchall(
            "SELECT status, COUNT(*) AS count FROM tasks GROUP BY status"
        )
    ]
    badcases = [
        dict(row)
        for row in await db.fetchall(
            "SELECT status, COUNT(*) AS count FROM badcases GROUP BY status"
        )
    ]

    # 步骤 5：返回概览数据，前端可继续按 task 查看 trace。
    return {
        "totals": totals,
        "layers": layers,
        "llm": llm,
        "approvals": approvals,
        "task_status": task_status,
        "badcases": badcases,
        "recent_traces": await list_traces(db, limit=10),
    }
