"""评测集执行入口：金标集、阈值与场景清单。

`make test` 和 CI 的 `itinerary-eval` 使用同一套 runner 与阈值。
"""

import pytest

from itinerary_agent.eval.loader import (
    DEFAULT_CASES_DIR,
    DEFAULT_THRESHOLDS,
    load_cases,
)
from itinerary_agent.eval.runner import (
    check_thresholds,
    load_thresholds,
    run_all,
)
from tests import test_scenarios


async def test_eval_thresholds_pass():
    results = await run_all(DEFAULT_CASES_DIR)
    failures = check_thresholds(results, load_thresholds(DEFAULT_THRESHOLDS))
    assert not failures, failures
    for name, result in results.items():
        assert result.total > 0, f"{name} has no cases"


@pytest.mark.parametrize(
    "case", load_cases(DEFAULT_CASES_DIR)["scenario"], ids=lambda case: case["id"]
)
def test_scenario_manifest(case):
    # 场景清单保证评测集和端到端测试不脱节。
    assert callable(getattr(test_scenarios, case["test"]))
