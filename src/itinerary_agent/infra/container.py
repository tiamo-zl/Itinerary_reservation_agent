"""组合根：把配置、数据库和可观测组件装配在一起。

只有这里允许知道具体实现；业务层通过接口拿依赖。
M1 起增加编排服务的装配，M2/M3 会继续挂载 Checkpoint、工具、知识层。
"""

from dataclasses import dataclass

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.db import Database
from itinerary_agent.observability.tracing import TraceRecorder


@dataclass
class Container:
    """进程内依赖容器。

    资源生命周期跟随 FastAPI lifespan；测试可以替换 model/orchestrator。
    """

    settings: Settings
    db: Database
    traces: TraceRecorder

    model: object | None = None
    orchestrator: object | None = None
    tools: object | None = None
    knowledge: object | None = None
    control: object | None = None
    checkpointer: object | None = None
    rules: object | None = None
    audit: object | None = None
    policy_store: object | None = None
    conn: aiosqlite.Connection | None = None

    async def start(self) -> None:
        await self.db.connect()

        # live 模式才接入真实模型和 Milvus；scripted 模式保持完全离线。
        if self.settings.model_mode == "live":
            await self._init_live_model_and_knowledge()

        # 没有显式注入工具时，默认装配 mock 外部系统（M2）。
        if self.tools is None:
            self.tools = self._default_tools()
        # M2 起使用 SQLite Checkpoint；测试可注入 MemorySaver 跳过持久化。
        if self.checkpointer is None:
            self.conn = await aiosqlite.connect(self.settings.sqlite_path)
            self.checkpointer = AsyncSqliteSaver(self.conn)
            await self.checkpointer.setup()
        # 没有显式注入 orchestrator 时，按当前依赖自动装配。
        if self.orchestrator is None:
            self.orchestrator = self.build_orchestrator()

    async def stop(self) -> None:
        await self.db.close()
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def _init_live_model_and_knowledge(self) -> None:
        """按 live 模式装配真实模型网关与制度检索。"""
        if self.model is None:
            from itinerary_agent.model_gateway.gateway import OpenAIChatGateway

            self.model = OpenAIChatGateway(self.settings, self.db)

        if self.knowledge is None:
            from itinerary_agent.knowledge.milvus_store import MilvusClauseStore
            from itinerary_agent.knowledge.policy_store import PolicyStore
            from itinerary_agent.knowledge.service import KnowledgeService
            from itinerary_agent.model_gateway.embeddings import DashScopeEmbedder

            self.policy_store = PolicyStore(self.db)
            await self.policy_store.init()
            self.knowledge = KnowledgeService(
                embedder=DashScopeEmbedder(self.settings),
                policy_store=self.policy_store,
                dense_store=MilvusClauseStore(self.settings),
                policy_version=self.settings.policy_version,
                seed_top_k=self.settings.policy_seed_top_k,
                graph_hops=self.settings.policy_graph_hops,
                max_expanded_clauses=self.settings.policy_max_expanded_clauses,
            )

    def _default_tools(self):
        """M2 默认工具集：查询与用户信息，全部走 mock 适配器。"""
        from itinerary_agent.adapters.mock.inventory import MockFlightInventory, MockHotelInventory
        from itinerary_agent.adapters.mock.users import MockUserDirectory
        from itinerary_agent.tools.builtin import build_builtin_registry
        from itinerary_agent.tools.registry import ToolRegistry
        from itinerary_agent.tools.service import ToolService

        registry = build_builtin_registry(
            ToolRegistry(), MockFlightInventory(), MockHotelInventory(),
            MockUserDirectory(),
        )
        return ToolService(registry)

    def build_orchestrator(self):
        """装配编排服务；M1 只依赖模型和 Trace。"""
        from itinerary_agent.orchestration.service import OrchestrationService

        return OrchestrationService(
            model=self.model or self._default_model(),
            traces=self.traces,
            tools=self.tools,
            knowledge=self.knowledge,
            control=self.control,
            checkpointer=self.checkpointer,
            db=self.db,
            rules=self.rules,
            audit=self.audit,
        )

    def _default_model(self):
        # 无 API Key 时的离线默认实现；真实模型在 M3 接入。
        from itinerary_agent.adapters.scripted_model import ScriptedModelGateway

        return ScriptedModelGateway([])


def build_container(settings: Settings | None = None) -> Container:
    """根据配置创建容器；测试可传入临时 SQLite 路径。"""
    settings = settings or Settings()
    db = Database(settings.sqlite_path)
    return Container(settings=settings, db=db, traces=TraceRecorder(db))
