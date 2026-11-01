"""结构化日志：上下文注入与脱敏。"""

import io
import json
import logging

from itinerary_agent.observability.logging import (
    ContextFilter,
    RedactingJsonFormatter,
    bind_request_context,
    clear_request_context,
)


def test_json_logging_redacts_and_injects_context():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingJsonFormatter("%(message)s"))
    handler.addFilter(ContextFilter(
        service="itinerary-agent", environment="test", version="0.1.0"
    ))
    logger = logging.getLogger("test-json-logging")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    bind_request_context("req-1", "demo-company", "u001")
    try:
        logger.info(
            "contact 13812345678",
            extra={"authorization": "Bearer secret"},
        )
    finally:
        clear_request_context()
        logger.handlers = []

    data = json.loads(stream.getvalue())
    assert data["request_id"] == "req-1"
    assert data["tenant_id"] == "demo-company"
    assert data["user_id"] == "u001"
    assert data["service"] == "itinerary-agent"
    assert data["authorization"] == "[REDACTED]"
    assert "[PHONE]" in data["message"]
