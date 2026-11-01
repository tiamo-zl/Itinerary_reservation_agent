"""结构化日志：JSON、上下文关联与脱敏。"""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

from itinerary_agent.infra.config import Settings
from itinerary_agent.observability import tracing
from itinerary_agent.security.pii import scrub

_request_id: ContextVar[str] = ContextVar("log_request_id", default="")
_tenant_id: ContextVar[str] = ContextVar("log_tenant_id", default="")
_user_id: ContextVar[str] = ContextVar("log_user_id", default="")

_SENSITIVE_KEYS = {
    "authorization", "cookie", "set-cookie", "api_key", "apikey",
    "jwt_secret", "password", "secret", "token",
}


def bind_request_context(request_id: str, tenant_id: str,
                         user_id: str) -> None:
    _request_id.set(request_id)
    _tenant_id.set(tenant_id)
    _user_id.set(user_id)


def clear_request_context() -> None:
    _request_id.set("")
    _tenant_id.set("")
    _user_id.set("")


class ContextFilter(logging.Filter):
    """把 trace/task/request 上下文注入每条日志。"""

    def __init__(self, service: str = "itinerary-agent",
                 environment: str = "local", version: str = "0.1.0"):
        super().__init__()
        self.service = service
        self.environment = environment
        self.version = version

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service
        record.environment = self.environment
        record.version = self.version
        record.trace_id = tracing.current_trace_id() or ""
        record.span_id = tracing.current_span_id() or ""
        record.task_id = tracing.current_task_id() or ""
        record.request_id = _request_id.get()
        record.tenant_id = _tenant_id.get()
        record.user_id = _user_id.get()
        return True


class RedactingJsonFormatter(JsonFormatter):
    """JSON 输出 + 敏感字段/手机号/证件号脱敏。"""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        for key in list(log_record):
            value = log_record[key]
            if key.lower() in _SENSITIVE_KEYS:
                log_record[key] = "[REDACTED]"
            elif isinstance(value, str):
                log_record[key] = scrub(value)


def configure_logging(settings: Settings) -> None:
    """生产/本地输出 JSON；pytest 环境保持默认，避免污染断言输出。"""
    if settings.environment == "test":
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingJsonFormatter("%(message)s"))
    handler.addFilter(ContextFilter(
        service=settings.otel_service_name,
        environment=settings.environment,
        version=settings.otel_service_version,
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # uvicorn 的 logger 交给 root，避免同一行输出两次。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
