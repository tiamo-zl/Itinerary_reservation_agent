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
OUTBOX_BACKLOG = Gauge(
    "itinerary_outbox_backlog",
    "Pending or retryable outbox events",
)
TOOL_CALLS = Counter(
    "itinerary_tool_calls_total",
    "Tool invocations by tool, status and error code",
    ["tool", "status", "code"],
)
TOOL_DURATION = Histogram(
    "itinerary_tool_duration_seconds",
    "Tool latency",
    ["tool"],
)
RETENTION_DELETED = Counter(
    "itinerary_retention_deleted_rows_total",
    "Rows deleted by the retention worker",
    ["table"],
)
CIRCUIT_TRANSITIONS = Counter(
    "itinerary_model_circuit_transitions_total",
    "Model circuit breaker state transitions",
    ["provider", "to"],
)
CIRCUIT_REJECTED = Counter(
    "itinerary_model_circuit_rejected_total",
    "Model calls rejected because the circuit is open",
    ["provider"],
)
CIRCUIT_REDIS_ERRORS = Counter(
    "itinerary_model_circuit_redis_errors_total",
    "Circuit breaker Redis access failures",
)
CIRCUIT_OPEN = Gauge(
    "itinerary_model_circuit_open",
    "Whether the provider circuit is open (1) or closed (0)",
    ["provider"],
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

APPROVAL_DECISION_SECONDS = Histogram(
    "itinerary_approval_decision_seconds",
    "Time from approval creation to decision",
    ["decision"],
)
APPROVAL_RECOVERY_SECONDS = Histogram(
    "itinerary_approval_recovery_seconds",
    "Time for the worker to resume a task after an approval event",
    ["status"],
)

QUALITY_SAMPLES = Counter(
    "itinerary_quality_samples_total",
    "Near-line quality samples evaluated",
)
QUALITY_CHECKS = Counter(
    "itinerary_quality_checks_total",
    "Near-line quality checks by check and status",
    ["check", "status"],
)
QUALITY_PASS_RATIO = Gauge(
    "itinerary_quality_pass_ratio",
    "Near-line quality pass ratio per check for the latest batch",
    ["check"],
)

JUDGE_RESULTS = Counter(
    "itinerary_judge_results_total",
    "LLM judge verdicts",
    ["verdict"],
)
JUDGE_SCORE = Histogram(
    "itinerary_judge_score",
    "LLM judge score (0-5)",
    buckets=(0, 1, 2, 3, 4, 5),
)
JUDGE_PASS_RATIO = Gauge(
    "itinerary_judge_pass_ratio",
    "Pass ratio in the latest judge batch",
)
JUDGE_ERRORS = Counter(
    "itinerary_judge_errors_total",
    "LLM judge failures by code",
    ["code"],
)
