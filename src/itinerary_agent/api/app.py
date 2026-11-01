"""HTTP 应用入口。

网关层只做接入相关的事情（路由、健康检查、后续的鉴权/SSE），
不直接持有 LangGraph 状态，也不调用外部业务系统。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from itinerary_agent.api.auth import PUBLIC_PATHS, AuthError, AuthService
from itinerary_agent.api.routes import build_router
from itinerary_agent.application.errors import AppError
from itinerary_agent.infra.container import Container


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


def create_app(container: Container) -> FastAPI:
    """创建 FastAPI 应用，并把容器绑定到应用生命周期。

    测试里传入临时路径的 Container，避免污染 ./data。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动时连接 PostgreSQL/Redis/Checkpoint；关闭时统一释放。
        await container.start()
        yield
        await container.stop()

    app = FastAPI(title="Itinerary Reservation Agent", lifespan=lifespan)
    app.state.container = container
    auth_service = AuthService(container.settings)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        """先认证再进业务路由；健康检查与静态页保持公开。"""
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        try:
            request.state.ctx = await auth_service.authenticate(request)
        except AuthError as exc:
            return JSONResponse(
                status_code=401,
                content={"error": exc.message, "code": exc.code},
            )

        ctx = request.state.ctx
        scope = _rate_limit_scope(request)
        decision = None
        if scope is not None and container.rate_limiter is not None:
            decision = await container.rate_limiter.check(
                scope, f"{ctx.tenant_id}:{ctx.user_id}"
            )
            if not decision.allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": "too many requests",
                        "code": "RATE_LIMITED",
                    },
                    headers={"Retry-After": str(decision.retry_after or 1)},
                )

        response = await call_next(request)
        if decision is not None:
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(
                decision.remaining
            )
        response.headers["X-Request-ID"] = ctx.request_id
        return response

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

    @app.get("/")
    async def index():
        # 最小 Web 聊天页；生产会替换成正式前端。
        return FileResponse(Path(__file__).parent / "static" / "chat.html")

    # /chat 与 /tasks/*：SSE 流式入口和任务查询。
    app.include_router(build_router(container))
    return app
