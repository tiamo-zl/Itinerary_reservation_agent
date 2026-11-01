"""评测用例与阈值加载。"""

import json
from pathlib import Path

DEFAULT_CASES_DIR = Path(__file__).resolve().parents[3] / "tests/eval/cases"
DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[3] / "tests/eval/thresholds.json"


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def case_files(cases_dir: Path) -> dict[str, Path]:
    return {
        "slot": cases_dir / "slot_cases.jsonl",
        "policy": cases_dir / "policy_cases.jsonl",
        "retrieval": cases_dir / "retrieval_cases.jsonl",
        "approval": cases_dir / "approval_cases.jsonl",
        "prompt": cases_dir / "prompt_cases.jsonl",
        "badcase": cases_dir / "badcase_cases.jsonl",
        "scenario": cases_dir / "scenario_cases.jsonl",
    }


def load_cases(cases_dir: Path) -> dict[str, list[dict]]:
    """加载全部存在的用例文件；缺失的 suite 返回空列表。"""
    loaded = {}
    for suite, path in case_files(cases_dir).items():
        loaded[suite] = load_jsonl(path) if path.exists() else []
    return loaded
