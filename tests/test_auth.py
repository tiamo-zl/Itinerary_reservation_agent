"""鉴权：mock 兼容、JWT 校验与生产启动保护。"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from itinerary_agent.api.app import create_app
from itinerary_agent.infra.config import Settings
from itinerary_agent.infra.container import build_container
from itinerary_agent.mock_services.identity import create_identity_app
from tests.db_utils import make_test_settings

JWT_SECRET = "test-secret-0123456789abcdef0123456789"
ISSUER = "itinerary-agent-local"
AUDIENCE = "itinerary-agent"


def _token(secret: str = JWT_SECRET, expires_in: int = 300,
           **overrides) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": "u002",
        "tenant_id": "demo-company",
        "roles": ["employee", "approver"],
        "scopes": ["approval:read", "approval:decide"],
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


def _jwt_app():
    settings = make_test_settings(
        auth_mode="jwt", jwt_secret=JWT_SECRET,
        jwt_issuer=ISSUER, jwt_audience=AUDIENCE,
    )
    return create_app(build_container(settings))


def test_mock_header_auth_still_works(tmp_path):
    app = create_app(build_container(make_test_settings()))
    with TestClient(app) as client:
        response = client.get(
            "/conversations", headers={"X-Mock-User": "u002"}
        )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_jwt_requires_and_accepts_token(tmp_path):
    app = _jwt_app()
    with TestClient(app) as client:
        assert client.get("/conversations").status_code == 401

        response = client.get(
            "/conversations",
            headers={"Authorization": f"Bearer {_token()}"},
        )
    assert response.status_code == 200


def test_jwt_rejects_expired_token(tmp_path):
    app = _jwt_app()
    with TestClient(app) as client:
        response = client.get(
            "/conversations",
            headers={"Authorization": f"Bearer {_token(expires_in=-10)}"},
        )
    assert response.status_code == 401


def test_jwt_rejects_wrong_issuer(tmp_path):
    app = _jwt_app()
    with TestClient(app) as client:
        response = client.get(
            "/conversations",
            headers={
                "Authorization": f"Bearer {_token(iss='evil-issuer')}"
            },
        )
    assert response.status_code == 401


def test_production_rejects_mock_auth():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="prod", auth_mode="mock")


def test_production_jwt_requires_secret():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="prod", auth_mode="jwt")


def test_mock_idp_issues_verifiable_token():
    settings = make_test_settings(
        auth_mode="jwt", jwt_secret=JWT_SECRET,
        jwt_issuer=ISSUER, jwt_audience=AUDIENCE,
    )
    app = create_identity_app(settings)
    with TestClient(app) as client:
        response = client.post("/token", json={"user": "u002"})
    assert response.status_code == 200

    claims = jwt.decode(
        response.json()["access_token"],
        JWT_SECRET,
        algorithms=["HS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
    )
    assert claims["sub"] == "u002"
    assert claims["tenant_id"] == "demo-company"
    assert "approval:decide" in claims["scopes"]
