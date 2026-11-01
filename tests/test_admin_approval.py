from fastapi.testclient import TestClient

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.container import build_container
from tests.db_utils import make_test_settings


def test_admin_reject(tmp_path):
    # 管理员驳回不存在的审批单应返回 404，而不是静默成功。
    settings = make_test_settings()
    container = build_container(settings)
    app = create_app(container)
    with TestClient(app) as client:
        resp = client.post(
            "/admin/approvals/missing/reject",
            headers={"X-Mock-User": "u002"},
            json={"comment": "超标"},
        )
    assert resp.status_code == 404
