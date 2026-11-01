"""OpenTelemetry 初始化。

P0 默认关闭；设置 OTEL_ENABLED=true 后启用 SDK、自动埋点和 OTLP 导出。
业务 trace 投影仍由 TraceRecorder 写入 PostgreSQL，供自建控制台查询。
"""

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ParentBased,
    TraceIdRatioBased,
)

from itinerary_agent.infra.config import Settings

logger = logging.getLogger(__name__)
_provider: TracerProvider | None = None


def setup_telemetry(settings: Settings, app=None) -> TracerProvider | None:
    """初始化 OTel；重复调用只复用同一 provider。"""
    global _provider
    if not settings.otel_enabled:
        return None
    if _provider is None:
        resource = Resource.create({
            "service.name": settings.otel_service_name,
            "service.version": settings.otel_service_version,
            "deployment.environment": settings.environment,
        })
        provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(
                TraceIdRatioBased(settings.otel_trace_sampling_ratio)
            ),
        )
        if settings.otel_exporter_otlp_endpoint:
            provider.add_span_processor(BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=settings.otel_exporter_otlp_endpoint
                )
            ))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument(tracer_provider=provider)
        PsycopgInstrumentor().instrument(tracer_provider=provider)
        RedisInstrumentor().instrument(tracer_provider=provider)
        _provider = provider
        logger.info("OpenTelemetry enabled for %s",
                    settings.otel_service_name)

    if app is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=_provider)
    return _provider


def shutdown_telemetry() -> None:
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
