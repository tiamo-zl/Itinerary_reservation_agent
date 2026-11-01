"""Prometheus 指标端点。"""

from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.container import build_container
from tests.db_utils import make_test_settings


def test_metrics_endpoint_exposes_http_metrics(tmp_path):
    app = create_app(build_container(make_test_settings()))
    with TestClient(app) as client:
        client.get("/conversations", headers={"X-Mock-User": "u002"})
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "itinerary_http_requests_total" in response.text
    assert 'path="/conversations"' in response.text
