from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from itinerary_agent.infra.db import Database

logger = logging.getLogger(__name__)

_current_trace: ContextVar[str | None] = ContextVar("current_trace", default=None)
_current_span: ContextVar[str | None] = ContextVar("current_span", default=None)


class TraceRecorder:
    def __init__(self, db: Database):
        self.db = db

    def start_trace(self, trace_id: str | None = None) -> str:
        trace_id = trace_id or uuid4().hex
        _current_trace.set(trace_id)
        _current_span.set(None)
        return trace_id

    def current_trace_id(self) -> str | None:
        return _current_trace.get()

    @asynccontextmanager
    async def span(self, name: str, layer: str, **attributes):
        trace_id = _current_trace.get() or self.start_trace()
        span_id = uuid4().hex
        parent_id = _current_span.get()
        started_at = datetime.now(UTC)
        started = perf_counter()
        token = _current_span.set(span_id)
        status = "ok"
        try:
            yield span_id
        except Exception as exc:
            status = "error"
            attributes["error"] = str(exc)
            raise
        finally:
            _current_span.reset(token)
            duration_ms = (perf_counter() - started) * 1000
            await self._write_span(
                span_id, trace_id, parent_id, name, layer, status,
                started_at, duration_ms, attributes,
            )

    async def _write_span(self, span_id, trace_id, parent_id, name, layer,
                          status, started_at, duration_ms, attributes) -> None:
        try:
            await self.db.execute(
                "INSERT INTO spans (span_id, trace_id, parent_span_id, name, layer, "
                "status, start_time, duration_ms, attributes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    span_id, trace_id, parent_id, name, layer, status,
                    started_at.isoformat(), duration_ms,
                    json.dumps(attributes, ensure_ascii=False, default=str),
                ),
            )
        except Exception:
            logger.exception("failed to persist span %s", name)
