"""用 import 边界守住七层依赖方向。"""

import ast
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
