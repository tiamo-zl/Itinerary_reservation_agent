"""JSONL 评测用例加载器。

用例只描述输入和可确定性断言的期望，不绑定自由文本回答。
"""

import json
from pathlib import Path

CASES_DIR = Path(__file__).parent / "cases"


def load_cases(name: str) -> list[dict]:
    path = CASES_DIR / name
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
