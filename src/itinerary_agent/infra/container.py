"""组合根：把配置、数据库和可观测组件装配在一起。

只有这里允许知道具体实现；业务层通过接口拿依赖。
M0-M4 依次挂载基础设施、编排、工具、Checkpoint、制度检索、审批与下单。
"""

from dataclasses import dataclass
from pathlib import Path

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.database import Database
from itinerary_agent.observability.tracing import TraceRecorder


@dataclass
class Container:
    """进程内依赖容器。

    资源生命周期跟随 FastAPI lifespan；测试可以替换 model/orchestrator。
    """

    settings: Settings
    db: Database
    traces: TraceRecorder
    redis: object | None = None

    model: object | None = None
    orchestrator: object | None = None
    tools: object | None = None
    knowledge: object | None = None
    control: object | None = None
    checkpointer: object | None = None
    checkpointer_pool: object | None = None
    memory: object | None = None
    rules: object | None = None
    audit: object | None = None
    policy_store: object | None = None
    approvals: object | None = None
    booking: object | None = None
    poller: object | None = None
    flight_inventory: object | None = None
    hotel_inventory: object | None = None
    user_directory: object | None = None

    # 分层重构：仓储与用例服务在 start() 中装配。
    task_repo: object | None = None
    trace_repo: object | None = None
    conversation_repo: object | None = None
    approval_repo: object | None = None
    feedback_repo: object | None = None
    outbox_repo: object | None = None
    outbox_relay: object | None = None
    task_queries: object | None = None
    trace_queries: object | None = None
    conversation_queries: object | None = None
    approval_queries: object | None = None
    feedback_service: object | None = None
    readiness: object | None = None

    async def start(self, role: str = "api") -> None:
        """按依赖顺序装配整个进程。

        role=api：HTTP 进程，不启动后台轮询；
        role=worker：后台进程，负责审批轮询/outbox/保留清理。

        步骤：
        1. 连接 PostgreSQL/Redis 并准备短期/长期记忆；
        2. live 模式装配真实模型与 Milvus；
        3. 创建 mock 审批与下单系统；
        4. 组装工具注册表；
        5. 装载差标规则、审计和动作控制；
        6. 初始化 Postgres Checkpoint；
        7. 编译编排图；
        8. 装配仓储与应用服务；
        9. worker 角色启动审批轮询器。
        """
        # 步骤 1：基础设施与记忆。
        await self.db.connect()
        if self.redis is None:
            from redis.asyncio import Redis

            # 只创建客户端；连接失败由 /readyz 暴露，聊天读路径仍可降级。
            self.redis = Redis.from_url(
                self.settings.redis_url, decode_responses=True
            )
        if self.memory is None:
            from itinerary_agent.knowledge.memory import MemoryStore

            self.memory = MemoryStore(self.db)

        # 步骤 2：live 模式才接入真实模型和 Milvus；scripted 保持离线。
        if self.settings.model_mode == "live":
            await self._init_live_model_and_knowledge()

        # 步骤 3：审批与下单是 mock 外部系统，先于工具注册创建。
        if self.approvals is None:
            from itinerary_agent.adapters.mock.approval import MockApprovalSystem

            self.approvals = MockApprovalSystem(
                self.db,
                self.settings.mock_approval_delay_seconds,
                auto_approve=self.settings.mock_approval_auto_approve,
            )
        if self.booking is None:
            from itinerary_agent.adapters.mock.booking import MockBookingSystem

            self.booking = MockBookingSystem(self.db)

        # 步骤 4：没有显式注入工具时，默认装配 mock 外部系统。
        if self.tools is None:
            self.tools = self._default_tools()

        # 步骤 5：控制层（规则、审计、动作准入）。
        if self.audit is None:
            from itinerary_agent.control.audit import AuditLog

            self.audit = AuditLog(self.db)
        if self.rules is None:
            from itinerary_agent.control.rules import load_rules

            self.rules = load_rules(
                Path(__file__).resolve().parents[3]
                / "config/policies/demo-company.yaml"
            )
        if self.control is None:
            from itinerary_agent.control.service import ControlService

            self.control = ControlService(self.rules, self.audit)

        # 步骤 6：初始化 Checkpoint。独立连接池，避免 checkpoint 事务
        # 与业务写事务互相阻塞。
        if self.checkpointer is None:
            await self._init_checkpointer()

        # 步骤 7：编译编排图。
        if self.orchestrator is None:
            self.orchestrator = self.build_orchestrator()

        # 步骤 8：装配仓储与用例服务（依赖 db、编排器和审批系统）。
        self._init_application_services()

        # 步骤 9：只有 worker 角色启动后台任务，API 进程保持无状态。
        if role == "worker":
            if self.outbox_relay is None:
                from itinerary_agent.workers.outbox_relay import OutboxRelay

                self.outbox_relay = OutboxRelay(
                    self.outbox_repo,
                    self.task_repo,
                    self.orchestrator,
                    interval=self.settings.outbox_poll_interval,
                    max_attempts=self.settings.outbox_max_attempts,
                    lease_seconds=self.settings.outbox_lease_seconds,
                )
                self.outbox_relay.start()
            # 自动审批是 demo 开关；外部系统没有 outbox 事件时用轮询兜底。
            if self.settings.mock_approval_auto_approve and self.poller is None:
                from itinerary_agent.orchestration.approval_poller import (
                    ApprovalPoller,
                )

                self.poller = ApprovalPoller(
                    self.db, self.approvals, self.orchestrator
                )
                self.poller.start()

    async def stop(self) -> None:
        if self.outbox_relay is not None:
            await self.outbox_relay.stop()
            self.outbox_relay = None
        if self.poller is not None:
            await self.poller.stop()
        if self.approvals is not None:
            await self.approvals.stop()
        if self.checkpointer_pool is not None:
            await self.checkpointer_pool.close()
            self.checkpointer_pool = None
        if self.redis is not None:
            await self.redis.aclose()
            self.redis = None
        await self.db.close()

    async def _init_checkpointer(self) -> None:
        """PostgreSQL Checkpoint：独立连接池 + 自动建表。"""
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        self.checkpointer_pool = AsyncConnectionPool(
            conninfo=self.settings.database_url,
            min_size=1,
            max_size=5,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )
        await self.checkpointer_pool.open()
        await self.checkpointer_pool.wait()
        self.checkpointer = AsyncPostgresSaver(self.checkpointer_pool)
        await self.checkpointer.setup()

    async def _init_live_model_and_knowledge(self) -> None:
        """按 live 模式装配真实模型网关与制度检索。"""
        if self.model is None:
            from itinerary_agent.model_gateway.gateway import OpenAIChatGateway

            self.model = OpenAIChatGateway(
                self.settings, self.db, traces=self.traces
            )

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
        """默认工具集：查询、用户、审批、下单，全部走 mock 适配器。"""
        from itinerary_agent.adapters.mock.inventory import (
            MockFlightInventory,
            MockHotelInventory,
        )
        from itinerary_agent.adapters.mock.users import MockUserDirectory
        from itinerary_agent.tools.builtin import (
            build_builtin_registry,
            register_approval_tools,
            register_booking_tools,
        )
        from itinerary_agent.tools.registry import ToolRegistry
        from itinerary_agent.tools.service import ToolService

        registry = build_builtin_registry(
            ToolRegistry(),
            self.flight_inventory or MockFlightInventory(),
            self.hotel_inventory or MockHotelInventory(),
            self.user_directory or MockUserDirectory(),
        )
        register_approval_tools(registry, self.approvals)
        register_booking_tools(registry, self.booking)
        return ToolService(registry, traces=self.traces)

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
            memory=self.memory,
            rules=self.rules,
            audit=self.audit,
        )

    def _init_application_services(self) -> None:
        """装配 Controller → Application Service → Repository 三层。

        步骤：
        1. 仓储只依赖 Database，可被测试替换成 fake；
        2. 查询服务依赖仓储和编排读接口；
        3. 审批服务额外依赖外部审批系统。
        """
        from itinerary_agent.application.approval_queries import (
            ApprovalQueryService,
        )
        from itinerary_agent.application.conversation_queries import (
            ConversationQueryService,
        )
        from itinerary_agent.application.feedback_service import FeedbackService
        from itinerary_agent.application.health import ReadinessService
        from itinerary_agent.application.task_queries import TaskQueryService
        from itinerary_agent.application.trace_queries import TraceQueryService
        from itinerary_agent.infra.repositories import (
            PostgresApprovalRepository,
            PostgresConversationRepository,
            PostgresFeedbackRepository,
            PostgresOutboxRepository,
            PostgresTaskRepository,
            PostgresTraceRepository,
        )

        # 步骤 1：仓储。
        self.task_repo = self.task_repo or PostgresTaskRepository(self.db)
        self.trace_repo = self.trace_repo or PostgresTraceRepository(self.db)
        self.conversation_repo = (
            self.conversation_repo or PostgresConversationRepository(self.db)
        )
        self.approval_repo = (
            self.approval_repo or PostgresApprovalRepository(self.db)
        )
        self.feedback_repo = (
            self.feedback_repo or PostgresFeedbackRepository(self.db)
        )
        self.outbox_repo = (
            self.outbox_repo or PostgresOutboxRepository(self.db)
        )

        # 步骤 2：查询服务。
        self.task_queries = self.task_queries or TaskQueryService(
            self.task_repo, self.orchestrator
        )
        self.trace_queries = self.trace_queries or TraceQueryService(
            self.trace_repo, self.task_repo
        )
        self.conversation_queries = (
            self.conversation_queries or ConversationQueryService(
                self.conversation_repo, self.orchestrator
            )
        )
        self.feedback_service = (
            self.feedback_service or FeedbackService(self.feedback_repo)
        )

        # 步骤 3：审批查询 + 决策。
        self.approval_queries = self.approval_queries or ApprovalQueryService(
            self.approval_repo, self.task_repo, self.orchestrator,
            self.approvals, self.outbox_repo, self.db,
        )
        self.readiness = self.readiness or ReadinessService(
            self.db, self.redis, self.checkpointer
        )

    def _default_model(self):
        # 无 API Key 时的离线默认实现；真实模型在 M3 接入。
        from itinerary_agent.adapters.scripted_model import ScriptedModelGateway

        return ScriptedModelGateway([])


def build_container(settings: Settings | None = None) -> Container:
    """根据配置创建容器；测试可传入测试库 DATABASE_URL。"""
    settings = settings or Settings()
    db = Database(
        settings.database_url,
        min_size=settings.database_pool_min,
        max_size=settings.database_pool_max,
    )
    return Container(settings=settings, db=db, traces=TraceRecorder(db))
