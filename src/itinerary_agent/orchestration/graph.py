"""M1 主图：understand → plan → respond。

后续里程碑会在 plan 与 respond 之间插入 search / policy / approval / book，
但节点之间始终通过 TravelTaskState 通信。
"""

from functools import partial

from langgraph.graph import END, START, StateGraph

from itinerary_agent.orchestration.nodes.plan import plan
from itinerary_agent.orchestration.nodes.respond import respond
from itinerary_agent.orchestration.nodes.understand import understand
from itinerary_agent.orchestration.state import TravelTaskState


def route_after_understand(state: dict) -> str:
    """缺槽位时直接汇总（M1）；后续会改成等待用户补充。"""
    return "respond" if state["status"] == "WAITING_HUMAN" else "plan"


def build_graph(deps):
    """编译主图；checkpointer 由 service 注入（M1 用 MemorySaver）。"""
    graph = StateGraph(TravelTaskState)
    graph.add_node("understand", partial(understand, deps=deps))
    graph.add_node("plan", partial(plan, deps=deps))
    graph.add_node("respond", partial(respond, deps=deps))

    graph.add_edge(START, "understand")
    graph.add_conditional_edges(
        "understand", route_after_understand, {"respond": "respond", "plan": "plan"}
    )
    graph.add_edge("plan", "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=getattr(deps, "checkpointer", None))
