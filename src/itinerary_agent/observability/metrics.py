"""Prometheus 指标。

统一使用 `itinerary_` 前缀；路径标签必须做模板化，避免高基数。
"""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS = Counter(
    "itinerary_http_requests_total",
    "HTTP requests by method, route and status",
    ["method", "path", "status"],
)
HTTP_DURATION = Histogram(
    "itinerary_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)
MODEL_CALLS = Counter(
    "itinerary_model_calls_total",
    "Model calls by provider, status and fallback",
    ["provider", "status", "fallback"],
)
MODEL_ERRORS = Counter(
    "itinerary_model_errors_total",
    "Model errors by provider and code",
    ["provider", "code"],
)
MODEL_TOKENS = Counter(
    "itinerary_model_tokens_total",
    "Model tokens by provider and kind",
    ["provider", "kind"],
)
MODEL_COST = Counter(
    "itinerary_model_cost_usd_total",
    "Model cost in USD by provider",
    ["provider"],
)
LLM_CACHE_HITS = Counter(
    "itinerary_llm_cache_hits_total", "LLM cache hits"
)
LLM_CACHE_MISSES = Counter(
    "itinerary_llm_cache_misses_total", "LLM cache misses"
)
RATE_LIMITED = Counter(
    "itinerary_rate_limited_total",
    "Requests rejected by the rate limiter",
    ["scope"],
)
SSE_CONNECTIONS = Gauge(
    "itinerary_sse_connections", "Active SSE connections"
)
OUTBOX_EVENTS = Counter(
    "itinerary_outbox_events_total",
    "Outbox events processed by status",
    ["status"],
)


def normalize_path(path: str) -> str:
    """把带 ID 的路径折叠成模板，控制 Prometheus 标签基数。"""
    prefixes = (
        "/tasks/", "/traces/", "/conversations/", "/approvals/",
        "/badcases/", "/admin/approvals/", "/sessions/",
    )
    for prefix in prefixes:
        if path.startswith(prefix) and path != prefix:
            return f"{prefix}{{id}}"
    return path


def observe_http(method: str, path: str, status: int,
                 duration_seconds: float) -> None:
    route = normalize_path(path)
    HTTP_REQUESTS.labels(method=method, path=route, status=str(status)).inc()
    HTTP_DURATION.labels(method=method, path=route).observe(duration_seconds)
