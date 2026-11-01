"""用 import 边界守住七层依赖方向。"""

import ast
import re
from pathlib import Path


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_api_does_not_import_langgraph_or_openai():
    for path in Path("src/itinerary_agent/api").rglob("*.py"):
        names = imports(path)
        assert not any(name.startswith("langgraph") for name in names), path
        assert not any(name.startswith("openai") for name in names), path


def test_orchestration_does_not_import_model_sdk():
    for path in Path("src/itinerary_agent/orchestration").rglob("*.py"):
        names = imports(path)
        assert not any(name.startswith("openai") for name in names), path
        assert not any(name.startswith("pymilvus") for name in names), path


def test_api_has_no_sql_or_direct_database_access():
    """Controller 不得直接访问数据库或拼 SQL。"""
    sql = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b")
    for path in Path("src/itinerary_agent/api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "container.db" not in text, path
        assert not sql.search(text), path


def test_application_does_not_depend_on_http_or_infra():
    """应用服务只依赖端口与领域模型，可注入 fake repository 单测。"""
    for path in Path("src/itinerary_agent/application").rglob("*.py"):
        names = imports(path)
        for forbidden in ("fastapi", "starlette", "itinerary_agent.api",
                          "itinerary_agent.infra"):
            assert not any(name.startswith(forbidden) for name in names), (
                path, forbidden
            )
