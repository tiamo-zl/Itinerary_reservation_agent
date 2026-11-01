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
    llm_cache: object | None = None
    breaker: object | None = None
    rate_limiter: object | None = None
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
    http_client: object | None = None
    flight_inventory: object | None = None
    hotel_inventory: object | None = None
    user_directory: object | None = None

    # 分层重构：仓储与用例服务在 start() 中装配。
    task_repo: object | None = None
    trace_repo: object | None = None
    conversation_repo: object | None = None
    approval_repo: object | None = None
    idempotency_repo: object | None = None
    feedback_repo: object | None = None
    outbox_repo: object | None = None
    message_repo: object | None = None
    memory_repo: object | None = None
    span_repo: object | None = None
    model_call_repo: object | None = None
    outbox_relay: object | None = None
    retention_worker: object | None = None
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
        from itinerary_agent.infra.repositories import (
            PostgresApprovalRepository,
            PostgresIdempotencyRepository,
            PostgresMemoryRepository,
            PostgresMessageRepository,
        )

        self.message_repo = (
            self.message_repo or PostgresMessageRepository(self.db)
        )
        self.memory_repo = (
            self.memory_repo or PostgresMemoryRepository(self.db)
        )
        self.approval_repo = (
            self.approval_repo or PostgresApprovalRepository(self.db)
        )
        self.idempotency_repo = (
            self.idempotency_repo or PostgresIdempotencyRepository(self.db)
        )
        if self.memory is None:
            from itinerary_agent.knowledge.memory import MemoryStore

            self.memory = MemoryStore(self.message_repo, self.memory_repo)

        # 步骤 2：live 模式才接入真实模型和 Milvus；scripted 保持离线。
        if self.settings.model_mode == "live":
            await self._init_live_model_and_knowledge()

        # 步骤 3：审批与下单是外部系统，先于工具注册创建。
        if self.settings.adapter_mode == "real":
            raise RuntimeError("ADAPTER_MODE=real is not implemented")
        if self.settings.adapter_mode == "http":
            self._init_http_adapters()
        else:
            if self.approvals is None:
                from itinerary_agent.adapters.mock.approval import (
                    MockApprovalSystem,
                )

                self.approvals = MockApprovalSystem(
                    self.approval_repo,
                    self.settings.mock_approval_delay_seconds,
                    auto_approve=self.settings.mock_approval_auto_approve,
                )
            if self.booking is None:
                from itinerary_agent.adapters.mock.booking import (
                    MockBookingSystem,
                )

                self.booking = MockBookingSystem(self.idempotency_repo)

        # 步骤 4：没有显式注入工具时，默认装配外部系统适配器。
        if self.tools is None:
            self.tools = self._default_tools()

        # 步骤 5：控制层（规则、审计、动作准入）。
        if self.audit is None:
            from itinerary_agent.infra.repositories import PostgresAuditLog

            self.audit = PostgresAuditLog(self.db)
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

        # 步骤 7：编译编排图。任务仓储必须先于编排器创建，
        # 以便恢复路径获取租约。
        if self.task_repo is None:
            from itinerary_agent.infra.repositories.task_repository import (
                PostgresTaskRepository,
            )

            self.task_repo = PostgresTaskRepository(self.db)
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
                    self.task_repo, self.approval_repo,
                    self.approvals, self.orchestrator,
                )
                self.poller.start()
            # 保留清理只处理投影/缓存/已结束事件，不删除业务状态。
            if self.settings.retention_enabled and self.retention_worker is None:
                from itinerary_agent.workers.retention import RetentionWorker

                self.retention_worker = RetentionWorker(
                    self.span_repo, self.outbox_repo, self.llm_cache,
                    self.idempotency_repo, self.settings,
                    self.settings.retention_interval_seconds,
                )
                self.retention_worker.start()

    async def stop(self) -> None:
        if self.retention_worker is not None:
            await self.retention_worker.stop()
            self.retention_worker = None
        if self.outbox_relay is not None:
            await self.outbox_relay.stop()
            self.outbox_relay = None
        if self.poller is not None:
            await self.poller.stop()
        if self.approvals is not None:
            await self.approvals.stop()
        if self.http_client is not None:
            await self.http_client.close()
            self.http_client = None
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
        if self.llm_cache is None:
            from itinerary_agent.infra.repositories.llm_cache_repository import (
                PostgresLLMCache,
            )
            from itinerary_agent.model_gateway.cache import RedisLLMCache

            backend = self.settings.llm_cache_backend
            if backend in {"auto", "redis"} and self.redis is not None:
                self.llm_cache = RedisLLMCache(
                    self.redis,
                    self.settings.llm_cache_ttl_seconds,
                    prefix=f"{self.settings.environment}:llm:",
                )
            elif backend in {"auto", "postgres"} and self.db is not None:
                self.llm_cache = PostgresLLMCache(
                    self.db, self.settings.llm_cache_ttl_seconds
                )

        if self.model_call_repo is None:
            from itinerary_agent.infra.repositories import (
                PostgresModelCallRepository,
            )

            self.model_call_repo = PostgresModelCallRepository(self.db)

        if (
            self.breaker is None
            and self.settings.circuit_breaker_enabled
            and self.redis is not None
        ):
            from itinerary_agent.model_gateway.circuit import (
                RedisCircuitBreaker,
            )

            self.breaker = RedisCircuitBreaker(
                self.redis, self.settings.environment,
                failure_threshold=self.settings.circuit_failure_threshold,
                cooldown_seconds=self.settings.circuit_cooldown_seconds,
                trial_seconds=self.settings.circuit_trial_seconds,
            )

        if self.model is None:
            from itinerary_agent.model_gateway.gateway import OpenAIChatGateway

            self.model = OpenAIChatGateway(
                self.settings, ledger=self.model_call_repo,
                traces=self.traces, cache=self.llm_cache,
                breaker=self.breaker,
            )

        if self.knowledge is None:
            from itinerary_agent.infra.repositories import PostgresPolicyStore
            from itinerary_agent.knowledge.milvus_store import MilvusClauseStore
            from itinerary_agent.knowledge.service import KnowledgeService
            from itinerary_agent.model_gateway.embeddings import DashScopeEmbedder

            self.policy_store = PostgresPolicyStore(self.db)
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

    def _init_http_adapters(self) -> None:
        """装配独立 mock 依赖服务的 HTTP 适配器。"""
        from itinerary_agent.adapters.http.approval import HttpApprovalSystem
        from itinerary_agent.adapters.http.booking import HttpBookingSystem
        from itinerary_agent.adapters.http.client import JsonHttpClient
        from itinerary_agent.adapters.http.inventory import (
            HttpFlightInventory,
            HttpHotelInventory,
        )
        from itinerary_agent.adapters.http.users import HttpUserDirectory

        if self.http_client is None:
            self.http_client = JsonHttpClient(
                self.settings.mock_deps_url,
                timeout=self.settings.upstream_timeout_seconds,
                max_retries=self.settings.upstream_max_retries,
            )
        client = self.http_client
        self.user_directory = self.user_directory or HttpUserDirectory(client)
        self.flight_inventory = (
            self.flight_inventory or HttpFlightInventory(client)
        )
        self.hotel_inventory = self.hotel_inventory or HttpHotelInventory(client)
        # 审批读取仍走本地投影；提交/决定同步写投影。
        self.approvals = self.approvals or HttpApprovalSystem(
            client, mirror=self.approval_repo
        )
        self.booking = self.booking or HttpBookingSystem(client)

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
            memory=self.memory,
            rules=self.rules,
            audit=self.audit,
            task_repo=self.task_repo,
            lease_seconds=self.settings.task_lease_seconds,
            prompt_version=self.settings.prompt_version,
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
            self.approvals, self.outbox_repo, self.db, self.audit,
        )
        from itinerary_agent.infra.rate_limit import RateLimiter

        self.rate_limiter = self.rate_limiter or RateLimiter(
            self.redis, self.settings
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
    from itinerary_agent.infra.repositories.span_repository import (
        PostgresSpanRepository,
    )

    span_repo = PostgresSpanRepository(db)
    return Container(
        settings=settings,
        db=db,
        span_repo=span_repo,
        traces=TraceRecorder(span_repo, otel_enabled=settings.otel_enabled),
    )
