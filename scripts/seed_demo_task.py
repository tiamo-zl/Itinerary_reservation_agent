"""创建一个可人工验收的 P0 演示任务。

使用脚本化模型走完理解/规划/查询/差标，最终停在审批 interrupt，
不调用真实模型或外部网络。运行模式与当前配置一致：

    make demo-seed
    make demo-seed ARGS="--adapter-mode http"

输出 task_id / trace_id / approval_id，供控制台和观测系统检索。
"""

import argparse
import asyncio
import json

from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container

UNDERSTAND = (
    '{"origin_city":"上海","destination_city":"北京",'
    '"start_date":"2026-11-03","end_date":"2026-11-05"}'
)
PLAN = '{"steps":["search_flights","search_hotels"]}'
RESPOND = "方案已生成。"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed a P0 demo task")
    parser.add_argument(
        "--adapter-mode", choices=["mock", "http"], default=None,
        help="与运行中的 API 保持一致；默认读取 Settings",
    )
    parser.add_argument("--mock-deps-url", default="http://127.0.0.1:9003")
    parser.add_argument("--user", default="u001")
    parser.add_argument("--session", default="p0-manual")
    parser.add_argument("--trace-id", default="p0-manual-trace")
    parser.add_argument(
        "--message",
        default="下周二去北京出差两天，住在王府井附近，1000 元以内",
    )
    parser.add_argument("--json", action="store_true")
    return parser


async def main() -> int:
    args = _parser().parse_args()
    settings = Settings()
    # 演示任务始终使用脚本模型；不因本机 .env 的 live 配置去连 Milvus。
    updates = {"model_mode": "scripted"}
    if args.adapter_mode:
        updates["adapter_mode"] = args.adapter_mode
    if (updates.get("adapter_mode") or settings.adapter_mode) == "http":
        # 宿主机脚本访问 compose 服务时不能用容器名 mock-deps。
        updates["mock_deps_url"] = args.mock_deps_url
    settings = settings.model_copy(update=updates)

    container = build_container(settings)
    container.model = ScriptedModelGateway([UNDERSTAND, PLAN, RESPOND])
    await container.start(role="api")
    try:
        ctx = RequestContext(
            trace_id=args.trace_id, tenant_id="demo-company",
            user_id=args.user, roles=["employee"],
            scopes=["chat", "task:read"],
            session_id=args.session,
        )
        events = [
            event async for event in container.orchestrator.start_turn(
                ctx, args.message
            )
        ]
        task_id = events[0].data["task_id"]
        interrupt = next(
            (event for event in events if event.type == "interrupt"), None
        )
        result = {
            "task_id": task_id,
            "trace_id": events[0].data["trace_id"],
            "session_id": args.session,
            "status": events[-1].data.get("status"),
            "approval_id": (
                interrupt.data["human_request"].get("approval_id")
                if interrupt else None
            ),
            "interrupt": (
                interrupt.data["human_request"].get("kind")
                if interrupt else None
            ),
            "gateway": "http://127.0.0.1:8081",
        }
    finally:
        await asyncio.sleep(0.3)
        await container.stop()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
