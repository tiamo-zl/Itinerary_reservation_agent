"""离线 demo 模型：常见中文差旅表达的结构化解析。"""

import json

from itinerary_agent.adapters.scripted_model import (
    DemoScriptedModelGateway,
    _parse_demo_request,
)
from itinerary_agent.domain.models import CallContext, ModelTier


def test_parse_demo_request():
    parsed = _parse_demo_request(
        "下周二去北京出差两天，住王府井附近，预算 2000 元"
    )
    assert parsed["destination_city"] == "北京"
    assert parsed["start_date"] == "下周二"
    assert parsed["duration_days"] == 2
    assert parsed["budget_limit"] == 2000
    assert parsed["hotel_area"] == "王府井"
    assert parsed["origin_city"] == "上海"
    assert parsed["need_flight"] is True
    assert parsed["need_hotel"] is True


def test_parse_demo_request_hotel_only():
    parsed = _parse_demo_request("只住酒店，上海，明天，800 元")
    assert parsed["need_flight"] is False
    assert parsed["need_hotel"] is True
    assert parsed["destination_city"] == "上海"
    assert parsed["start_date"] == "明天"
    assert parsed["budget_limit"] == 800


async def test_demo_gateway_returns_valid_shapes():
    gateway = DemoScriptedModelGateway([])
    ctx = CallContext(
        trace_id="demo-trace", tenant_id="demo-company",
        task_id="demo-task", purpose="understand",
    )
    completion = await gateway.complete(
        ctx,
        [{"role": "user", "content": "下周二去北京出差两天，预算 2000 元"}],
        ModelTier.LIGHT,
    )
    parsed = json.loads(completion.text)
    assert parsed["destination_city"] == "北京"

    plan = await gateway.complete(
        CallContext(
            trace_id="demo-trace", tenant_id="demo-company",
            task_id="demo-task", purpose="plan",
        ),
        [{"role": "user", "content": "{}"}],
        ModelTier.REASONING,
    )
    assert json.loads(plan.text)["steps"]

    summary = await gateway.complete(
        CallContext(
            trace_id="demo-trace", tenant_id="demo-company",
            task_id="demo-task", purpose="summarize",
        ),
        [{"role": "user", "content": "{}"}],
        ModelTier.STANDARD,
    )
    assert summary.text
