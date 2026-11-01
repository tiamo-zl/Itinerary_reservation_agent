"""认证服务：本地 mock / JWT / OIDC。

生产环境必须使用 JWT 或 OIDC；mock 只允许 local/test。
OIDC 通过 JWKS 校验签名，JWK 集合由 PyJWT 缓存。
"""

import asyncio
from uuid import uuid4

import jwt
from fastapi import Request

from itinerary_agent.api.context import (
    mock_context,
    request_id_of,
    scopes_for_roles,
)
from itinerary_agent.domain.models import RequestContext
from itinerary_agent.infra.config import Settings

PUBLIC_PATHS = {
    "/", "/health", "/healthz", "/readyz", "/docs",
    "/openapi.json", "/redoc", "/favicon.ico",
}


class AuthError(Exception):
    def __init__(self, message: str = "unauthorized",
                 code: str = "UNAUTHORIZED"):
        super().__init__(message)
        self.message = message
        self.code = code


class AuthService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._jwk_client = None

    async def authenticate(self, request: Request) -> RequestContext:
        if self.settings.auth_mode == "mock":
            return mock_context(request)

        token = self._bearer_token(request)
        claims = await self._decode(token)
        roles = [str(role) for role in claims.get("roles", [])]
        scopes = [
            str(scope) for scope in
            (claims.get("scopes") or scopes_for_roles(roles))
        ]
        return RequestContext(
            trace_id=request.headers.get("X-Trace-Id") or uuid4().hex,
            tenant_id=str(claims["tenant_id"]),
            user_id=str(claims["sub"]),
            roles=roles,
            scopes=scopes,
            auth_method=self.settings.auth_mode,
            request_id=request_id_of(request),
            session_id=request.headers.get("X-Session-Id", "default-session"),
        )

    @staticmethod
    def _bearer_token(request: Request) -> str:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthError("missing bearer token")
        return token

    async def _decode(self, token: str) -> dict:
        try:
            if self.settings.auth_mode == "jwt":
                return jwt.decode(
                    token,
                    self.settings.jwt_secret,
                    algorithms=["HS256"],
                    audience=self.settings.jwt_audience,
                    issuer=self.settings.jwt_issuer,
                    options={"require": ["exp", "sub", "tenant_id"]},
                )
            return await self._decode_oidc(token)
        except jwt.PyJWTError as exc:
            raise AuthError("invalid or expired token") from exc

    async def _decode_oidc(self, token: str) -> dict:
        from jwt import PyJWKClient

        if self._jwk_client is None:
            self._jwk_client = PyJWKClient(
                self.settings.oidc_jwks_url, cache_keys=True
            )
        signing_key = await asyncio.to_thread(
            self._jwk_client.get_signing_key_from_jwt, token
        )
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=self.settings.oidc_audience,
            issuer=self.settings.oidc_issuer,
            options={"require": ["exp", "sub", "tenant_id"]},
        )
