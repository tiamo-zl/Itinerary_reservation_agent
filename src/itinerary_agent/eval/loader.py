"""评测用例与阈值加载。"""

import json
from pathlib import Path

DEFAULT_CASES_DIR = Path(__file__).resolve().parents[3] / "tests/eval/cases"
DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[3] / "tests/eval/thresholds.json"
DEFAULT_DATASET = Path(__file__).resolve().parents[3] / "tests/eval/dataset.json"

SPLITS = ("golden", "regression", "holdout")


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


def load_dataset(cases_dir: Path) -> dict:
    path = cases_dir.parent / "dataset.json"
    if path.exists():
        return load_json(path)
    return {"version": "unknown", "default_split": {}}


def load_cases(cases_dir: Path,
               splits: set[str] | None = None) -> dict[str, list[dict]]:
    """加载用例并注入 dataset_version / split。

    splits 为 None 表示全部；CI 默认传 {"golden", "regression"}，
    holdout 不参与调参和常规门禁。
    """
    meta = load_dataset(cases_dir)
    defaults = meta.get("default_split", {})
    loaded = {}
    for suite, path in case_files(cases_dir).items():
        cases = load_jsonl(path) if path.exists() else []
        for case in cases:
            case.setdefault("dataset_version", meta.get("version", "unknown"))
            case.setdefault("split", defaults.get(suite, "golden"))
        if splits is not None:
            cases = [case for case in cases if case["split"] in splits]
        loaded[suite] = cases
    return loaded
