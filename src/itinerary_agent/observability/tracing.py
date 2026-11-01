"""Trace 记录器。

数据模型与 OpenTelemetry 对齐（trace_id / span_id / parent_span_id）。
OTel 开启时同时创建 OTel span；无论是否开启，都异步/同步落库到
PostgreSQL 的 spans 投影，供自建控制台查询。写入失败绝不影响业务。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager, nullcontext
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

logger = logging.getLogger(__name__)


class SpanStore(Protocol):
    async def write_span(self, span_id: str, trace_id: str,
                         parent_id: str | None, name: str, layer: str,
                         status: str, started_at: datetime,
                         duration_ms: float, attributes: dict) -> None: ...

# ContextVar 让 trace/span 上下文在 async 调用链中自动传递，
# 不需要每层函数都显式接收 trace_id 参数。
_current_trace: ContextVar[str | None] = ContextVar("current_trace", default=None)
_current_span: ContextVar[str | None] = ContextVar("current_span", default=None)
_current_task: ContextVar[str | None] = ContextVar("current_task", default=None)


def _otel_attributes(attributes: dict) -> dict:
    """OTel 只接受原始类型；嵌套结构转成字符串。"""
    result = {}
    for key, value in attributes.items():
        if value is None:
            continue
        result[key] = value if isinstance(
            value, (str, int, float, bool)
        ) else str(value)
    return result


class TraceRecorder:
    """一次用户请求 = 一个 trace；每个层/节点操作 = 一个 span。"""

    def __init__(self, span_store: SpanStore,
                 otel_enabled: bool = False):
        self.span_store = span_store
        self._tracer = (
            trace.get_tracer("itinerary_agent") if otel_enabled else None
        )

    def start_trace(self, trace_id: str | None = None) -> str:
        """开始或沿用一次 trace；沿用时不打断当前 span 父子关系。"""
        trace_id = trace_id or uuid4().hex
        if _current_trace.get() == trace_id:
            # 同一 trace 内节点显式绑定 trace 时，不要清空 parent span。
            return trace_id
        _current_trace.set(trace_id)
        # 新 trace 必须清空 span 上下文，避免复用旧请求的 parent。
        _current_span.set(None)
        _current_task.set(None)
        return trace_id

    def set_task(self, task_id: str | None) -> None:
        """标记当前 trace 所属任务，供 Span 归属和按 task 聚合。"""
        _current_task.set(task_id)

    def current_trace_id(self) -> str | None:
        return _current_trace.get()

    @asynccontextmanager
    async def span(self, name: str, layer: str, **attributes):
        """创建一个 span，并在退出时落盘。

        嵌套调用时自动把当前 span 作为 parent，从而形成调用树。
        即使异常发生也会记录 error 状态，然后继续向上抛出。
        """
        trace_id = _current_trace.get() or self.start_trace()
        task_id = _current_task.get()
        if task_id:
            attributes.setdefault("task_id", task_id)
        span_id = uuid4().hex
        parent_id = _current_span.get()
        started_at = datetime.now(UTC)
        started = perf_counter()
        token = _current_span.set(span_id)
        status = "ok"
        span_cm = (
            self._tracer.start_as_current_span(
                name, attributes=_otel_attributes(attributes)
            )
            if self._tracer is not None
            else nullcontext()
        )
        try:
            with span_cm as otel_span:
                try:
                    yield span_id
                except Exception as exc:
                    status = "error"
                    attributes["error"] = str(exc)
                    if otel_span is not None:
                        otel_span.record_exception(exc)
                        otel_span.set_status(
                            Status(StatusCode.ERROR, str(exc))
                        )
                    raise
                else:
                    if otel_span is not None:
                        otel_span.set_status(Status(StatusCode.OK))
        finally:
            _current_span.reset(token)
            duration_ms = (perf_counter() - started) * 1000
            await self._write_span(
                span_id, trace_id, parent_id, name, layer, status,
                started_at, duration_ms, attributes,
            )

    async def _write_span(self, span_id, trace_id, parent_id, name, layer,
                          status, started_at, duration_ms, attributes) -> None:
        """持久化 span；观测写入不允许反向破坏业务主流程。"""
        try:
            await self.span_store.write_span(
                span_id, trace_id, parent_id, name, layer, status,
                started_at, duration_ms, attributes,
            )
        except Exception:
            logger.exception("failed to persist span %s", name)


def current_trace_id() -> str | None:
    return _current_trace.get()


def current_span_id() -> str | None:
    return _current_span.get()


def current_task_id() -> str | None:
    return _current_task.get()
