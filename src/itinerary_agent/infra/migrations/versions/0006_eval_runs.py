"""Evaluation run history and baseline comparison

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
CREATE TABLE IF NOT EXISTS eval_runs (
  run_id TEXT PRIMARY KEY,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  status TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  splits JSONB NOT NULL,
  suites JSONB NOT NULL,
  prompt_version TEXT,
  git_sha TEXT,
  total_cases INTEGER NOT NULL DEFAULT 0,
  passed_cases INTEGER NOT NULL DEFAULT 0,
  failed_cases INTEGER NOT NULL DEFAULT 0,
  suite_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  threshold_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_started
  ON eval_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_eval_runs_dataset
  ON eval_runs (dataset_version, started_at DESC);

CREATE TABLE IF NOT EXISTS eval_case_results (
  run_id TEXT NOT NULL REFERENCES eval_runs(run_id) ON DELETE CASCADE,
  suite TEXT NOT NULL,
  case_id TEXT NOT NULL,
  passed BOOLEAN NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (run_id, suite, case_id)
);

CREATE INDEX IF NOT EXISTS idx_eval_case_results_case
  ON eval_case_results (suite, case_id, run_id);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS eval_case_results;
DROP TABLE IF EXISTS eval_runs;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
