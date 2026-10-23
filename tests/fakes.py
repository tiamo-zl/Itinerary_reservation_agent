"""测试用依赖装配。

不启动真实模型/外部系统，只验证编排与 HITL 流程。
"""

from itinerary_agent.adapters.mock.inventory import MockFlightInventory, MockHotelInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.orchestration.service import OrchestrationService
from itinerary_agent.tools.builtin import build_builtin_registry
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


class ScriptedDeps:
    def __init__(self, checkpointer):
        self.checkpointer = checkpointer
        # 顺序：understand → plan → respond（resume 后）→ 备用。
        self.model = ScriptedModelGateway([
            '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
            '{"steps":["search_flights","search_hotels"]}',
            '方案已生成。',
            '已确认。',
        ])
        registry = build_builtin_registry(
            ToolRegistry(), MockFlightInventory(), MockHotelInventory(), MockUserDirectory()
        )
        self.tools = ToolService(registry)
        self.traces = None
        self.knowledge = None
        self.control = None

    def build_service(self) -> OrchestrationService:
        return OrchestrationService(
            model=self.model,
            traces=self.traces,
            tools=self.tools,
            knowledge=self.knowledge,
            control=self.control,
            checkpointer=self.checkpointer,
        )
