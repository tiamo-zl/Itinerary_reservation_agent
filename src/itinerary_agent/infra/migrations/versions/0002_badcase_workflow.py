"""badcase workflow fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE badcases
  ADD COLUMN IF NOT EXISTS owner TEXT,
  ADD COLUMN IF NOT EXISTS sla_due_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS ticket_ref TEXT,
  ADD COLUMN IF NOT EXISTS regression_suite TEXT,
  ADD COLUMN IF NOT EXISTS regression_case JSONB,
  ADD COLUMN IF NOT EXISTS fixed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS reopened_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_badcases_owner ON badcases (owner);
CREATE INDEX IF NOT EXISTS idx_badcases_sla ON badcases (sla_due_at);
"""

DOWNGRADE_SQL = """
DROP INDEX IF EXISTS idx_badcases_sla;
DROP INDEX IF EXISTS idx_badcases_owner;
ALTER TABLE badcases
  DROP COLUMN IF EXISTS reopened_count,
  DROP COLUMN IF EXISTS fixed_at,
  DROP COLUMN IF EXISTS regression_case,
  DROP COLUMN IF EXISTS regression_suite,
  DROP COLUMN IF EXISTS ticket_ref,
  DROP COLUMN IF EXISTS sla_due_at,
  DROP COLUMN IF EXISTS owner;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
