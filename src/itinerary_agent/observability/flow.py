"""把一次 trace 转成编排图流转时间线。

静态 nodes/edges 描述全图；timeline 只包含本次实际走过的节点和边。
前端按 timeline 每秒推进一个节点或一条边。
"""

GRAPH_NODES = [
    {"id": "understand", "label": "理解需求"},
    {"id": "plan", "label": "规划"},
    {"id": "search", "label": "查询"},
    {"id": "policy", "label": "差标"},
    {"id": "approval", "label": "审批"},
    {"id": "confirm", "label": "确认"},
    {"id": "book", "label": "下单"},
    {"id": "respond", "label": "回复"},
]

GRAPH_EDGES = [
    {"id": "e-understand-plan", "source": "understand", "target": "plan",
     "label": "有目的地", "condition": "destination_city 非空"},
    {"id": "e-understand-respond", "source": "understand", "target": "respond",
     "label": "缺槽位", "condition": "destination_city 为空"},
    {"id": "e-plan-search", "source": "plan", "target": "search",
     "label": "生成步骤", "condition": "计划就绪"},
    {"id": "e-search-policy", "source": "search", "target": "policy",
     "label": "候选就绪", "condition": "查询完成"},
    {"id": "e-policy-approval", "source": "policy", "target": "approval",
     "label": "需审批", "condition": "requires_approval=true"},
    {"id": "e-policy-confirm", "source": "policy", "target": "confirm",
     "label": "通过 / 无需审批", "condition": "requires_approval=false"},
    {"id": "e-approval-confirm", "source": "approval", "target": "confirm",
     "label": "审批完成", "condition": "approved / rejected"},
    {"id": "e-confirm-book", "source": "confirm", "target": "book",
     "label": "已确认", "condition": "用户确认方案"},
    {"id": "e-confirm-respond", "source": "confirm", "target": "respond",
     "label": "取消", "condition": "用户取消"},
    {"id": "e-confirm-plan", "source": "confirm", "target": "plan",
     "label": "修改需求", "condition": "用户修改需求"},
    {"id": "e-book-respond", "source": "book", "target": "respond",
     "label": "下单完成", "condition": "写入成功"},
]

EDGE_BY_PAIR = {(edge["source"], edge["target"]): edge for edge in GRAPH_EDGES}
NODE_IDS = {node["id"] for node in GRAPH_NODES}
NODE_LABELS = {node["id"]: node["label"] for node in GRAPH_NODES}


def build_flow(spans: list[dict]) -> dict:
    """按 orchestration span 的先后顺序生成 node/edge timeline。"""
    timeline: list[dict] = []
    prev_node: str | None = None

    for span in spans:
        name = span["name"]
        if not name.startswith("orchestration.node."):
            continue
        node = name.removeprefix("orchestration.node.")
        if node not in NODE_IDS:
            continue
        # interrupt 恢复时同一节点会再执行一次，避免产生自环。
        if node == prev_node:
            continue
        if prev_node is not None:
            edge = EDGE_BY_PAIR.get((prev_node, node))
            timeline.append({
                "kind": "edge",
                "id": edge["id"] if edge else f"e-{prev_node}-{node}",
                "source": prev_node,
                "target": node,
                "label": edge["label"] if edge else "流转",
                "condition": edge["condition"] if edge else "",
                "at": span["start_time"],
            })
        timeline.append({
            "kind": "node",
            "node": node,
            "label": NODE_LABELS[node],
            "status": span["status"],
            "at": span["start_time"],
        })
        prev_node = node

    return {
        "nodes": GRAPH_NODES,
        "edges": GRAPH_EDGES,
        "timeline": timeline,
    }
