"""评测运行记录与用例级结果仓储。

eval_runs 保存一次评测的配置快照与 suite 指标；eval_case_results
保存每个用例的通过状态，用于基线对比中的 regression / fix 定位。
"""

import json

from itinerary_agent.infra.db import Database

_RUN_COLUMNS = (
    "run_id, started_at, finished_at, status, dataset_version, splits, "
    "suites, prompt_version, git_sha, total_cases, passed_cases, "
    "failed_cases, suite_metrics, threshold_failures, config, error"
)


class PostgresEvalRunRepository:
    def __init__(self, db: Database):
        self.db = db

    async def create(self, run: dict) -> None:
        await self.db.execute(
            "INSERT INTO eval_runs "
            "(run_id, started_at, status, dataset_version, splits, suites, "
            "prompt_version, git_sha, config) "
            "VALUES (?, ?, ?, ?, ?::jsonb, ?::jsonb, ?, ?, ?::jsonb)",
            (
                run["run_id"], run["started_at"], run["status"],
                run["dataset_version"], json.dumps(run["splits"]),
                json.dumps(run["suites"]), run.get("prompt_version"),
                run.get("git_sha"), json.dumps(run.get("config") or {}),
            ),
        )

    async def finish(self, run_id: str, *, status: str, finished_at,
                     total_cases: int, passed_cases: int,
                     failed_cases: int, suite_metrics: dict,
                     threshold_failures: list[str],
                     error: str | None = None) -> None:
        await self.db.execute(
            "UPDATE eval_runs SET status = ?, finished_at = ?, "
            "total_cases = ?, passed_cases = ?, failed_cases = ?, "
            "suite_metrics = ?::jsonb, threshold_failures = ?::jsonb, "
            "error = ? WHERE run_id = ?",
            (
                status, finished_at, total_cases, passed_cases,
                failed_cases, json.dumps(suite_metrics),
                json.dumps(threshold_failures), error, run_id,
            ),
        )

    async def add_case_results(self, run_id: str,
                               rows: list[dict]) -> None:
        async with self.db.transaction():
            for row in rows:
                await self.db.execute(
                    "INSERT INTO eval_case_results "
                    "(run_id, suite, case_id, passed, detail) "
                    "VALUES (?, ?, ?, ?, ?::jsonb) "
                    "ON CONFLICT (run_id, suite, case_id) DO NOTHING",
                    (
                        run_id, row["suite"], row["case_id"],
                        row["passed"], json.dumps(row.get("detail") or {}),
                    ),
                )

    async def get(self, run_id: str) -> dict | None:
        row = await self.db.fetchone(
            f"SELECT {_RUN_COLUMNS} FROM eval_runs WHERE run_id = ?",
            (run_id,),
        )
        return dict(row) if row else None

    async def latest_matching(self, *, dataset_version: str,
                              splits: list[str], suites: list[str],
                              exclude_run_id: str) -> dict | None:
        row = await self.db.fetchone(
            f"SELECT {_RUN_COLUMNS} FROM eval_runs "
            "WHERE run_id <> ? AND dataset_version = ? "
            "AND splits = ?::jsonb AND suites = ?::jsonb "
            "AND status IN ('passed', 'failed') "
            "ORDER BY started_at DESC LIMIT 1",
            (
                exclude_run_id, dataset_version, json.dumps(splits),
                json.dumps(suites),
            ),
        )
        return dict(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[dict]:
        rows = await self.db.fetchall(
            f"SELECT {_RUN_COLUMNS} FROM eval_runs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]

    async def case_results(self, run_id: str) -> list[dict]:
        rows = await self.db.fetchall(
            "SELECT suite, case_id, passed, detail "
            "FROM eval_case_results WHERE run_id = ? "
            "ORDER BY suite, case_id",
            (run_id,),
        )
        return [dict(row) for row in rows]
