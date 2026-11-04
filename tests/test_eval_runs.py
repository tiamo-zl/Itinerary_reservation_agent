"""评测运行记录与基线对比。"""

import json
from datetime import UTC, datetime

from itinerary_agent.eval.compare import compare_runs, render_comparison
from itinerary_agent.infra.repositories import PostgresEvalRunRepository
from tests.db_utils import open_test_db


def _run(run_id: str, started_at: datetime) -> dict:
    return {
        "run_id": run_id,
        "started_at": started_at,
        "status": "running",
        "dataset_version": "2026.11.02",
        "splits": ["golden", "regression"],
        "suites": ["slot"],
        "prompt_version": "v1",
        "git_sha": "abc",
        "config": {"model_mode": "scripted"},
    }


async def test_eval_run_repository_roundtrip():
    db = await open_test_db()
    repo = PostgresEvalRunRepository(db)
    older = _run("run-old", datetime(2026, 1, 1, tzinfo=UTC))
    newer = _run("run-new", datetime(2026, 1, 2, tzinfo=UTC))
    await repo.create(older)
    await repo.create(newer)
    await repo.finish(
        older["run_id"], status="passed",
        finished_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
        total_cases=2, passed_cases=2, failed_cases=0,
        suite_metrics={"slot": {"metrics": {"exact_match_rate": 1.0}}},
        threshold_failures=[],
    )
    await repo.add_case_results(older["run_id"], [
        {"suite": "slot", "case_id": "a", "passed": True, "detail": {}},
        {"suite": "slot", "case_id": "b", "passed": True, "detail": {}},
    ])

    row = await repo.get(older["run_id"])
    assert row is not None
    assert row["status"] == "passed"
    assert row["suite_metrics"]["slot"]["metrics"]["exact_match_rate"] == 1.0

    latest = await repo.latest_matching(
        dataset_version="2026.11.02",
        splits=["golden", "regression"],
        suites=["slot"],
        exclude_run_id=newer["run_id"],
    )
    assert latest is not None
    assert latest["run_id"] == older["run_id"]

    cases = await repo.case_results(older["run_id"])
    assert len(cases) == 2
    assert all(case["passed"] for case in cases)
    await db.close()


def test_compare_runs_detects_regressions_and_fixes():
    current = {
        "run_id": "cur",
        "dataset_version": "2026.11.02",
        "prompt_version": "v2",
        "git_sha": "new",
        "suite_metrics": {
            "slot": {"metrics": {"exact_match_rate": 0.9}},
        },
        "threshold_failures": ["slot.exact_match_rate"],
    }
    baseline = {
        "run_id": "base",
        "dataset_version": "2026.11.02",
        "prompt_version": "v1",
        "git_sha": "old",
        "suite_metrics": {
            "slot": {"metrics": {"exact_match_rate": 1.0}},
        },
        "threshold_failures": [],
    }
    current_cases = [
        {"suite": "slot", "case_id": "a", "passed": False},
        {"suite": "slot", "case_id": "b", "passed": True},
        {"suite": "slot", "case_id": "new", "passed": True},
    ]
    baseline_cases = [
        {"suite": "slot", "case_id": "a", "passed": True},
        {"suite": "slot", "case_id": "b", "passed": False},
        {"suite": "slot", "case_id": "old", "passed": True},
    ]

    result = compare_runs(current, baseline, current_cases, baseline_cases)
    assert result["has_regression"] is True
    assert [row["case_id"] for row in result["regressions"]] == ["a"]
    assert [row["case_id"] for row in result["fixes"]] == ["b"]
    assert [row["case_id"] for row in result["added"]] == ["new"]
    assert [row["case_id"] for row in result["removed"]] == ["old"]
    assert result["metric_regressions"][0]["metric"] == "exact_match_rate"
    assert "REGRESSION slot/a" in render_comparison(result)


def test_cli_records_two_runs_and_compares(tmp_path, capsys, monkeypatch):
    from itinerary_agent.eval import cli
    from tests.db_utils import TEST_DATABASE_URL

    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    assert cli.main([
        "--record", "--json", "--database-url", TEST_DATABASE_URL,
    ]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["run_id"]
    assert first["passed"] is True

    assert cli.main([
        "--record", "--json", "--database-url", TEST_DATABASE_URL,
        "--baseline", "latest", "--fail-on-regression",
    ]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["run_id"] != first["run_id"]
    assert second["comparison"]["baseline_run_id"] == first["run_id"]
    assert second["comparison"]["has_regression"] is False
    assert second["comparison"]["regressions"] == []
