"""本地 mock IdP：按 mock 用户签发 HS256 token。

生产环境应替换为真实 OIDC 提供方；这个服务只用于开发联调。
运行：uv run uvicorn --app-dir src itinerary_agent.mock_services.identity:app --port 9002
"""

from datetime import UTC, datetime, timedelta

import jwt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from itinerary_agent.api.context import MOCK_USERS, scopes_for_roles
from itinerary_agent.infra.config import Settings


class TokenRequest(BaseModel):
    user: str = "u001"


def create_identity_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Itinerary Mock IdP")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.post("/token")
    async def issue_token(payload: TokenRequest):
        user = MOCK_USERS.get(payload.user)
        if user is None:
            raise HTTPException(status_code=404, detail="unknown user")
        if settings.jwt_secret is None:
            raise HTTPException(
                status_code=503, detail="JWT_SECRET is not configured"
            )
        roles = list(user["roles"])
        now = datetime.now(UTC)
        claims = {
            "sub": payload.user,
            "tenant_id": user["tenant_id"],
            "roles": roles,
            "scopes": scopes_for_roles(roles),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + timedelta(hours=1),
        }
        return {
            "access_token": jwt.encode(
                claims,
                settings.jwt_secret.get_secret_value(),
                algorithm="HS256",
            ),
            "token_type": "bearer",
            "expires_in": 3600,
        }

    return app


app = create_identity_app(Settings())
