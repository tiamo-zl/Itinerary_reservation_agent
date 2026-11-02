"""Worker 进程入口。

与 API 使用同一镜像，但只启动后台任务，不对外提供业务路由。
运行：uv run uvicorn --app-dir src itinerary_agent.workers.main:app --port 8001
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from itinerary_agent.infra.container import Container, build_container
from itinerary_agent.observability.logging import configure_logging
from itinerary_agent.observability.telemetry import (
    setup_telemetry,
    shutdown_telemetry,
)


def create_worker_app(container: Container) -> FastAPI:
    configure_logging(container.settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await container.start(role="worker")
        yield
        await container.stop()
        shutdown_telemetry()

    app = FastAPI(title="Itinerary Agent Worker", lifespan=lifespan)
    app.state.container = container
    setup_telemetry(container.settings, app)

    @app.get("/metrics")
    async def metrics():
        return Response(
            content=generate_latest(), media_type=CONTENT_TYPE_LATEST
        )

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz():
        result = await container.readiness.check()
        result["checks"]["outbox_relay"] = (
            "ok" if container.outbox_relay is not None else "error"
        )
        result["checks"]["retention"] = (
            "ok" if (
                not container.settings.retention_enabled
                or container.retention_worker is not None
            ) else "error"
        )
        result["checks"]["business_metrics"] = (
            "ok" if (
                not container.settings.business_metrics_enabled
                or container.business_metrics_worker is not None
            ) else "error"
        )
        result["checks"]["quality_eval"] = (
            "ok" if (
                not container.settings.quality_eval_enabled
                or container.quality_eval_worker is not None
            ) else "error"
        )
        result["checks"]["judge"] = (
            "ok" if (
                not container.settings.judge_enabled
                or container.judge_worker is not None
            ) else "error"
        )
        if any(value != "ok" for value in result["checks"].values()):
            result["status"] = "degraded"
        return JSONResponse(
            status_code=200 if result["status"] == "ok" else 503,
            content=result,
        )

    return app


app = create_worker_app(build_container())
