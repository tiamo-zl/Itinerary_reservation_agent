"""Worker 进程入口。

与 API 使用同一镜像，但只启动后台任务，不对外提供业务路由。
运行：uv run uvicorn --app-dir src itinerary_agent.workers.main:app --port 8001
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from itinerary_agent.infra.container import Container, build_container


def create_worker_app(container: Container) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await container.start(role="worker")
        yield
        await container.stop()

    app = FastAPI(title="Itinerary Agent Worker", lifespan=lifespan)
    app.state.container = container

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        result = await container.readiness.check()
        result["checks"]["outbox_relay"] = (
            "ok" if container.outbox_relay is not None else "error"
        )
        if any(value != "ok" for value in result["checks"].values()):
            result["status"] = "degraded"
        return JSONResponse(
            status_code=200 if result["status"] == "ok" else 503,
            content=result,
        )

    return app


app = create_worker_app(build_container())
