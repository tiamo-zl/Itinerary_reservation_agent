from fastapi.testclient import TestClient

from itinerary_agent.adapters.scripted_model import ScriptedModelGateway
from itinerary_agent.api.app import create_app
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container


def test_chat_stream(tmp_path):
    # 用临时 SQLite 和脚本化模型，不访问真实网络。
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "chat.db")
    container = build_container(settings)
    container.model = ScriptedModelGateway([
        '{"destination_city":"北京","start_date":"2026-11-03","end_date":"2026-11-05"}',
        '{"steps":["search_flights"]}',
        '已生成方案。',
    ])
    # 不预构建 orchestrator：让 lifespan 按模型 + 默认 mock 工具自动装配。
    app = create_app(container)

    with TestClient(app) as client, client.stream(
        "POST", "/chat", json={"message": "下周二去北京"}
    ) as resp:
        body = "".join(resp.iter_text())

    assert resp.status_code == 200
    assert "event: result" in body
