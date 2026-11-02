"""HTTP 应用入口。

网关层只做接入相关的事情（路由、鉴权、限流、健康检查、SSE），
不直接持有 LangGraph 状态，也不调用外部业务系统。
"""

from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.trustedhost import TrustedHostMiddleware

from itinerary_agent.api.auth import PUBLIC_PATHS, AuthError, AuthService
from itinerary_agent.api.routes import build_router
from itinerary_agent.application.errors import AppError
from itinerary_agent.infra.container import Container
from itinerary_agent.observability.logging import (
    bind_request_context,
    clear_request_context,
    configure_logging,
)
from itinerary_agent.observability.metrics import RATE_LIMITED, observe_http
from itinerary_agent.observability.telemetry import (
    setup_telemetry,
    shutdown_telemetry,
)


def _rate_limit_scope(request: Request) -> str | None:
    """只对高成本/敏感写入口限流。"""
    if request.method != "POST":
        return None
    path = request.url.path
    if path == "/chat":
        return "chat"
    if path.startswith("/admin/approvals/"):
        return "approval"
    if path == "/feedback":
        return "feedback"
    return None


def _route_label(request: Request) -> str:
    """优先使用路由模板，避免 /tasks/{id} 造成高基数。"""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def create_app(container: Container) -> FastAPI:
    """创建 FastAPI 应用，并把容器绑定到应用生命周期。"""
    configure_logging(container.settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动时连接 PostgreSQL/Redis/Checkpoint；关闭时统一释放。
        await container.start()
        yield
        await container.stop()
        shutdown_telemetry()

    app = FastAPI(title="Itinerary Reservation Agent", lifespan=lifespan)
    app.state.container = container
    setup_telemetry(container.settings, app)
    auth_service = AuthService(container.settings)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        """认证 → 限流 → 业务路由；健康检查与静态页保持公开。"""
        started = perf_counter()
        if request.url.path in PUBLIC_PATHS:
            response = await call_next(request)
            observe_http(
                request.method, _route_label(request),
                response.status_code, perf_counter() - started,
            )
            return response

        try:
            request.state.ctx = await auth_service.authenticate(request)
        except AuthError as exc:
            observe_http(
                request.method, request.url.path, 401,
                perf_counter() - started,
            )
            return JSONResponse(
                status_code=401,
                content={"error": exc.message, "code": exc.code},
            )

        ctx = request.state.ctx
        bind_request_context(ctx.request_id, ctx.tenant_id, ctx.user_id)
        try:
            scope = _rate_limit_scope(request)
            decision = None
            if scope is not None and container.rate_limiter is not None:
                decision = await container.rate_limiter.check(
                    scope, f"{ctx.tenant_id}:{ctx.user_id}"
                )
                if not decision.allowed:
                    RATE_LIMITED.labels(scope=scope).inc()
                    observe_http(
                        request.method, request.url.path, 429,
                        perf_counter() - started,
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "too many requests",
                            "code": "RATE_LIMITED",
                        },
                        headers={
                            "Retry-After": str(decision.retry_after or 1),
                            "X-Trace-Id": ctx.trace_id,
                        },
                    )

            response = await call_next(request)
            if decision is not None:
                response.headers["X-RateLimit-Limit"] = str(decision.limit)
                response.headers["X-RateLimit-Remaining"] = str(
                    decision.remaining
                )
            response.headers["X-Request-ID"] = ctx.request_id
            # resume/chat 在路由层设置精确 trace；不要用网关上下文覆盖。
            if "x-trace-id" not in response.headers:
                response.headers["X-Trace-Id"] = ctx.trace_id
            observe_http(
                request.method, _route_label(request),
                response.status_code, perf_counter() - started,
            )
            return response
        finally:
            clear_request_context()

    # Starlette 的 add_middleware 会插到最前面（越后添加越靠外）。
    # 在 auth 之后注册，保证顺序是 TrustedHost → CORS → auth：
    # 预检请求不进入鉴权，Host 校验始终最先执行。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=container.settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID", "X-Trace-Id",
            "X-RateLimit-Limit", "X-RateLimit-Remaining",
        ],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=container.settings.trusted_hosts,
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        """应用层异常统一映射为 HTTP，handler 里不再散落 403/404 判断。"""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "code": exc.code},
        )

    @app.get("/health")
    async def health():
        # 兼容旧入口；新部署请使用 /healthz 与 /readyz。
        return {
            "status": "ok",
            "env": container.settings.environment,
        }

    @app.get("/healthz")
    async def healthz():
        """存活探针：进程能响应即可，不检查外部依赖。"""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        """就绪探针：数据库、Redis、Checkpoint 都可用才返回 200。"""
        result = await container.readiness.check()
        return JSONResponse(
            status_code=200 if result["status"] == "ok" else 503,
            content=result,
        )

    @app.get("/metrics")
    async def metrics():
        """Prometheus 抓取入口；不需要业务鉴权。"""
        return Response(
            content=generate_latest(), media_type=CONTENT_TYPE_LATEST
        )

    @app.get("/")
    async def index():
        # 最小 Web 聊天页；生产会替换成正式前端。
        return FileResponse(Path(__file__).parent / "static" / "chat.html")

    # /chat 与 /tasks/*：SSE 流式入口和任务查询。
    app.include_router(build_router(container))
    return app
