"""near-line quality findings

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
CREATE TABLE IF NOT EXISTS quality_findings (
  finding_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  trace_id TEXT,
  tenant_id TEXT NOT NULL,
  check_name TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, check_name)
);
CREATE INDEX IF NOT EXISTS idx_quality_findings_status
  ON quality_findings (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_findings_tenant
  ON quality_findings (tenant_id, created_at DESC);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS quality_findings;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
