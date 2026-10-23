"""组合根：把配置、数据库和可观测组件装配在一起。

只有这里允许知道具体实现；业务层通过接口拿依赖。
"""

from dataclasses import dataclass

from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.db import Database
from itinerary_agent.observability.tracing import TraceRecorder


@dataclass
class Container:
    """进程内依赖容器。

    M0 只包含基础设施；后续里程碑会继续挂载模型网关、工具、知识层等。
    资源生命周期跟随 FastAPI lifespan：start 建连接，stop 释放。
    """

    settings: Settings
    db: Database
    traces: TraceRecorder

    async def start(self) -> None:
        await self.db.connect()

    async def stop(self) -> None:
        await self.db.close()


def build_container(settings: Settings | None = None) -> Container:
    """根据配置创建容器；测试可传入临时 SQLite 路径。"""
    settings = settings or Settings()
    db = Database(settings.sqlite_path)
    return Container(settings=settings, db=db, traces=TraceRecorder(db))
