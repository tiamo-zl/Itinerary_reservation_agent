"""Trace 树重建与线上概览的纯计算。

SQL 已下沉到 infra/repositories/trace_repository.py；
这里只处理“拿到 span/快照之后怎么算”，便于单测和复用。
"""


def build_trace_tree(spans: list[dict]) -> list[dict]:
    """按 parent_span_id 把平铺的 span 还原成调用树。

    span 由仓储按 start_time 排好序；这里保持原顺序挂到父节点下，
    找不到父节点的 span（例如被采样丢弃）作为根节点返回。
    """
    nodes: dict[str, dict] = {}
    roots: list[dict] = []

    for row in spans:
        nodes[row["span_id"]] = {
            "span_id": row["span_id"],
            "parent_span_id": row["parent_span_id"],
            "name": row["name"],
            "layer": row["layer"],
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "attributes": row["attributes"],
            "children": [],
        }

    for node in nodes.values():
        parent = nodes.get(node["parent_span_id"])
        if parent:
            parent["children"].append(node)
        else:
            roots.append(node)
    return roots


def percentile(values: list[float], ratio: float) -> float:
    """最近秩百分位；数据量小，直接排序取下标即可。"""
    if not values:
        return 0.0
    values = sorted(values)
    index = min(len(values) - 1, int(len(values) * ratio))
    return values[index]


def build_overview(snapshot: dict, recent_traces: list[dict]) -> dict:
    """把仓储快照组装成前端概览 DTO。

    步骤：
    1. 补算错误率与 P95；
    2. 透传按层延迟、模型成本、审批/任务/badcase 分布；
    3. 附带最近 trace 方便跳转。
    """
    totals = dict(snapshot["totals"])
    totals["error_rate"] = (
        (totals["errors"] or 0) / totals["spans"] if totals["spans"] else 0.0
    )
    totals["p95_duration_ms"] = percentile(snapshot["durations"], 0.95)
    return {
        "totals": totals,
        "layers": snapshot["layers"],
        "llm": snapshot["llm"],
        "approvals": snapshot["approvals"],
        "task_status": snapshot["task_status"],
        "badcases": snapshot["badcases"],
        "recent_traces": recent_traces,
    }
