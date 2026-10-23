"""Trace 查询与树形重建。

七层纵向视图不是另一套存储：按 trace_id 取出 span，再按 parent_span_id
还原调用树即可。
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
