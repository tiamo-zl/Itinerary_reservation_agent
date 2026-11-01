"""结果汇总节点：流式生成给用户看的总结，并标记任务完成。"""

import logging

from langgraph.config import get_stream_writer

from itinerary_agent.domain.models import CallContext

logger = logging.getLogger(__name__)


async def respond(state: dict, deps) -> dict:
    """流式汇总；模型不可用时回退到固定文案，不阻断已完成的下单。"""
    template = deps.prompt("summarize")
    ctx = CallContext(
        trace_id=state["trace_id"], tenant_id=state["tenant_id"],
        task_id=state["task_id"], purpose="summarize",
        prompt_version=template.version,
    )
    chunks: list[str] = []
    try:
        async with deps.span(
            "orchestration.node.respond", "orchestration",
            trace_id=state["trace_id"],
        ):
            messages = [
                {"role": "system", "content": template.text},
                {"role": "user", "content": str(state.get("request"))},
            ]
            try:
                writer = get_stream_writer()
            except Exception:  # noqa: BLE001 - 直接调用节点时没有流上下文
                writer = None
            async for chunk in deps.model.stream(
                ctx, messages, deps.tier_standard
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                if writer is not None:
                    writer({"text": chunk})
    except Exception:
        logger.exception("summary stream failed; using fallback text")

    summary = "".join(chunks) or "差旅方案已处理完成。"
    return {"status": "COMPLETED", "summary": summary}
