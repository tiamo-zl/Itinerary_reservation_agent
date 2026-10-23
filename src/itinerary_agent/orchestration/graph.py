"""M1 主图：understand → plan → respond。

后续里程碑会在 plan 与 respond 之间插入 search / policy / approval / book，
但节点之间始终通过 TravelTaskState 通信。
"""

from functools import partial

from langgraph.graph import END, START, StateGraph

from itinerary_agent.orchestration.nodes.approval import request_approval
from itinerary_agent.orchestration.nodes.book import book
from itinerary_agent.orchestration.nodes.confirm import confirm
from itinerary_agent.orchestration.nodes.plan import plan
from itinerary_agent.orchestration.nodes.policy import policy_check
from itinerary_agent.orchestration.nodes.respond import respond
from itinerary_agent.orchestration.nodes.search import search
from itinerary_agent.orchestration.nodes.understand import understand
from itinerary_agent.orchestration.state import TravelTaskState


def route_after_understand(state: dict) -> str:
    """缺槽位时直接汇总（M1）；后续会改成等待用户补充。"""
    return "respond" if state["status"] == "WAITING_HUMAN" else "plan"


def route_after_policy(state: dict) -> str:
    """超标但允许审批时进入审批；其余进入用户确认。"""
    result = state.get("policy_result") or {}
    return "approval" if result.get("requires_approval") else "confirm"


def route_after_confirm(state: dict) -> str:
    if state["status"] == "CANCELLED":
        return "respond"
    if state["status"] == "PLANNING":
        return "plan"
    return "book"


def build_graph(deps):
    """编译主图；checkpointer 由 service 注入。"""
    graph = StateGraph(TravelTaskState)
    graph.add_node("understand", partial(understand, deps=deps))
    graph.add_node("plan", partial(plan, deps=deps))
    graph.add_node("search", partial(search, deps=deps))
    graph.add_node("policy", partial(policy_check, deps=deps))
    graph.add_node("approval", partial(request_approval, deps=deps))
    graph.add_node("confirm", partial(confirm, deps=deps))
    graph.add_node("book", partial(book, deps=deps))
    graph.add_node("respond", partial(respond, deps=deps))

    graph.add_edge(START, "understand")
    graph.add_conditional_edges(
        "understand", route_after_understand, {"respond": "respond", "plan": "plan"}
    )
    graph.add_edge("plan", "search")
    graph.add_edge("search", "policy")
    graph.add_conditional_edges(
        "policy", route_after_policy,
        {"approval": "approval", "confirm": "confirm"},
    )
    graph.add_edge("approval", "confirm")
    graph.add_conditional_edges(
        "confirm", route_after_confirm,
        {"book": "book", "respond": "respond", "plan": "plan"},
    )
    graph.add_edge("book", "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=getattr(deps, "checkpointer", None))
