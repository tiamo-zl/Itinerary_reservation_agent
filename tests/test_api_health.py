from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container


def test_health(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "app.db")
    container = build_container(settings)
    app = create_app(container)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
