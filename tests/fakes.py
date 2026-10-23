"""测试用依赖装配。

不启动真实模型/外部系统，只验证编排、差标、审批与 HITL 流程。
"""

from itinerary_agent.adapters.mock.inventory import MockFlightInventory, MockHotelInventory
from itinerary_agent.adapters.mock.users import MockUserDirectory
from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.control.rules import PolicyRules
from itinerary_agent.control.service import ControlService
from itinerary_agent.orchestration.service import OrchestrationService
from itinerary_agent.tools.builtin import build_builtin_registry, register_booking_tools
from itinerary_agent.tools.registry import ToolRegistry
from itinerary_agent.tools.service import ToolService


class _NoopAudit:
    async def record(self, *args, **kwargs):
        return None


class _FakeBooking:
    """内存幂等下单，避免测试依赖 SQLite。"""

    def __init__(self):
        self._results: dict[str, dict] = {}

    async def book(self, kind: str, key: str, payload: dict) -> dict:
        if key in self._results:
            return {**self._results[key], "replayed": True}
        result = {"booking_id": f"{kind}-test", "status": "confirmed"}
        self._results[key] = result
        return {**result, "replayed": False}


class ScriptedDeps:
    def __init__(self, checkpointer):
        self.checkpointer = checkpointer
        # 顺序：understand → plan → respond。
        self.model = ScriptedModelGateway([
            '{"origin_city":"上海","destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
            '{"steps":["search_flights","search_hotels"]}',
            '方案已生成。',
        ])
        registry = build_builtin_registry(
            ToolRegistry(), MockFlightInventory(), MockHotelInventory(), MockUserDirectory()
        )
        register_booking_tools(registry, _FakeBooking())
        self.tools = ToolService(registry)
        self.traces = None
        self.knowledge = None
        # 测试默认标准放行，避免把审批分支混进基础流程测试。
        self.rules = PolicyRules(
            version="2026.1", tenant_id="demo-company",
            defaults={
                "hotel": {"max_price_per_night": 1000},
                "flight": {"max_price": 5000},
            },
            rules=[],
        )
        self.audit = _NoopAudit()
        self.control = ControlService(self.rules, self.audit)

    def build_service(self) -> OrchestrationService:
        return OrchestrationService(
            model=self.model,
            traces=self.traces,
            tools=self.tools,
            knowledge=self.knowledge,
            control=self.control,
            checkpointer=self.checkpointer,
            rules=self.rules,
            audit=self.audit,
        )
