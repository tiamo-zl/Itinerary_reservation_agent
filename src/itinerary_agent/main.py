"""Uvicorn 入口。

启动命令：uv run uvicorn --app-dir src itinerary_agent.main:app --reload
"""

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.container import build_container

# 模块级 app 供 uvicorn 直接引用；真正的依赖装配在 build_container 内完成。
app = create_app(build_container())
