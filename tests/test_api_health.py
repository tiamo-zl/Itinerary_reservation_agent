from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.container import build_container
from tests.db_utils import make_test_settings


def test_health(tmp_path):
    # TestClient 会触发 lifespan：启动时连库，退出时关闭连接。
    settings = make_test_settings()
    container = build_container(settings)
    app = create_app(container)
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        assert client.get("/healthz").json() == {"status": "ok"}

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json()["checks"] == {
            "database": "ok",
            "redis": "ok",
            "checkpointer": "ok",
        }
