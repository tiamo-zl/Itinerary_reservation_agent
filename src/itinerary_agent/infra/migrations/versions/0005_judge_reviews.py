"""LLM judge human review queue

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE judge_results
  ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS human_score INTEGER,
  ADD COLUMN IF NOT EXISTS human_verdict TEXT,
  ADD COLUMN IF NOT EXISTS reviewer TEXT,
  ADD COLUMN IF NOT EXISTS review_comment TEXT,
  ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_judge_results_review
  ON judge_results (review_status, verdict, created_at DESC);
"""

DOWNGRADE_SQL = """
DROP INDEX IF EXISTS idx_judge_results_review;
ALTER TABLE judge_results
  DROP COLUMN IF EXISTS reviewed_at,
  DROP COLUMN IF EXISTS review_comment,
  DROP COLUMN IF EXISTS reviewer,
  DROP COLUMN IF EXISTS human_verdict,
  DROP COLUMN IF EXISTS human_score,
  DROP COLUMN IF EXISTS review_status;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
