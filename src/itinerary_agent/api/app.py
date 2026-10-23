"""HTTP 应用入口。

网关层只做接入相关的事情（路由、健康检查、后续的鉴权/SSE），
不直接持有 LangGraph 状态，也不调用外部业务系统。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from itinerary_agent.api.routes import build_router
from itinerary_agent.infra.container import Container


def create_app(container: Container) -> FastAPI:
    """创建 FastAPI 应用，并把容器绑定到应用生命周期。

    测试里传入临时路径的 Container，避免污染 ./data。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 启动时建立 SQLite 连接；关闭时统一释放。
        await container.start()
        yield
        await container.stop()

    app = FastAPI(title="Itinerary Reservation Agent", lifespan=lifespan)
    app.state.container = container

    @app.get("/health")
    async def health():
        # M0 只返回进程级健康；M3 起会扩展为检查 Milvus/模型配置。
        return {"status": "ok", "env": container.settings.env}

    @app.get("/")
    async def index():
        # 最小 Web 聊天页；生产会替换成正式前端。
        return FileResponse(Path(__file__).parent / "static" / "chat.html")

    # /chat 与 /tasks/*：SSE 流式入口和任务查询。
    app.include_router(build_router(container))
    return app
