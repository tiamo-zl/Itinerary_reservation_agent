"""评测数据集版本与 split 过滤。"""

from itinerary_agent.eval.loader import (
    DEFAULT_CASES_DIR,
    load_cases,
    load_dataset,
)


def test_dataset_metadata_and_split_injection():
    meta = load_dataset(DEFAULT_CASES_DIR)
    assert meta["version"] == "2026.11.02"

    ci_cases = load_cases(DEFAULT_CASES_DIR, {"golden", "regression"})
    ci_ids = {
        case["id"] for cases in ci_cases.values() for case in cases
    }
    assert "slot-holdout-this-sunday" not in ci_ids
    assert all(
        case["dataset_version"] == "2026.11.02"
        for cases in ci_cases.values() for case in cases
    )

    holdout = load_cases(DEFAULT_CASES_DIR, {"holdout"})
    holdout_ids = {
        case["id"] for cases in holdout.values() for case in cases
    }
    assert "slot-holdout-this-sunday" in holdout_ids
    assert all(
        case["split"] == "holdout"
        for cases in holdout.values() for case in cases
    )


def test_badcase_defaults_to_regression_split():
    cases = load_cases(DEFAULT_CASES_DIR, {"regression"})
    assert cases["badcase"]
    assert all(case["split"] == "regression" for case in cases["badcase"])
