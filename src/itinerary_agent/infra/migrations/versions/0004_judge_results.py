"""LLM judge results

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
CREATE TABLE IF NOT EXISTS judge_results (
  judge_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  trace_id TEXT,
  tenant_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  model TEXT NOT NULL,
  provider TEXT,
  score INTEGER NOT NULL,
  verdict TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, prompt_version)
);
CREATE INDEX IF NOT EXISTS idx_judge_results_verdict
  ON judge_results (verdict, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_judge_results_tenant
  ON judge_results (tenant_id, created_at DESC);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS judge_results;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
