"""带超时、重试和 trace 透传的 JSON HTTP 客户端。"""

import asyncio

import httpx
from opentelemetry import propagate


class UpstreamError(Exception):
    """外部系统错误；ToolService 用 code/retryable 做稳定映射。"""

    def __init__(self, message: str, code: str = "UPSTREAM_UNAVAILABLE",
                 retryable: bool = True, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class JsonHttpClient:
    def __init__(self, base_url: str, timeout: float = 5.0,
                 max_retries: int = 2, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout),
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, payload: dict) -> dict:
        return await self._request("POST", path, json=payload)

    async def _request(self, method: str, path: str, *,
                       params: dict | None = None,
                       json: dict | None = None) -> dict:
        """读请求与带幂等键的写请求可重试；4xx 不重试。"""
        for attempt in range(self.max_retries + 1):
            headers: dict[str, str] = {}
            # 有 OTel 上下文时自动注入 W3C traceparent；未启用时是 no-op。
            propagate.inject(headers)
            try:
                response = await self.client.request(
                    method, path, params=params, json=json, headers=headers,
                )
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
                raise UpstreamError(
                    f"upstream timeout: {method} {path}",
                    code="UPSTREAM_TIMEOUT", retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self.max_retries:
                    await self._backoff(attempt)
                    continue
                raise UpstreamError(
                    f"upstream unavailable: {method} {path}",
                    code="UPSTREAM_UNAVAILABLE", retryable=True,
                ) from exc

            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_retries:
                    await self._backoff(attempt, response)
                    continue
                raise UpstreamError(
                    f"upstream {response.status_code}: {method} {path}",
                    code="UPSTREAM_UNAVAILABLE",
                    retryable=True,
                    status_code=response.status_code,
                )
            if response.status_code >= 400:
                raise UpstreamError(
                    f"upstream {response.status_code}: {method} {path}",
                    code="UPSTREAM_BAD_RESPONSE",
                    retryable=False,
                    status_code=response.status_code,
                )
            try:
                return response.json()
            except ValueError as exc:
                raise UpstreamError(
                    f"upstream returned invalid JSON: {method} {path}",
                    code="UPSTREAM_BAD_RESPONSE", retryable=False,
                    status_code=response.status_code,
                ) from exc

        raise UpstreamError(
            f"upstream retries exhausted: {method} {path}",
            code="UPSTREAM_UNAVAILABLE", retryable=True,
        )

    @staticmethod
    async def _backoff(attempt: int,
                       response: httpx.Response | None = None) -> None:
        delay = min(0.2 * (2 ** attempt), 2.0)
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
        await asyncio.sleep(delay)
