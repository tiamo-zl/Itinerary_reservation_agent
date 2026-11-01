"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-11-01
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


UPGRADE_SQL = """
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  status TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  trace_id TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  version INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  lease_owner TEXT,
  lease_expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant_updated
  ON tasks (tenant_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status_updated
  ON tasks (status, updated_at);
CREATE INDEX IF NOT EXISTS idx_tasks_trace ON tasks (trace_id);
CREATE INDEX IF NOT EXISTS idx_tasks_lease ON tasks (lease_expires_at);

CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  session_id TEXT NOT NULL,
  task_id TEXT,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_messages_session
  ON messages (session_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_messages_task ON messages (task_id);

CREATE TABLE IF NOT EXISTS user_memories (
  memory_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL,
  source_task_id TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_user_memories_lookup
  ON user_memories (tenant_id, user_id, kind);

CREATE TABLE IF NOT EXISTS audit_log (
  decision_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  inputs_hash TEXT NOT NULL,
  rule_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  policy_version TEXT NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_log (trace_id);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log (task_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log (created_at DESC);

CREATE TABLE IF NOT EXISTS spans (
  span_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  parent_span_id TEXT,
  name TEXT NOT NULL,
  layer TEXT NOT NULL,
  status TEXT NOT NULL,
  start_time TIMESTAMPTZ NOT NULL,
  duration_ms DOUBLE PRECISION NOT NULL,
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  task_id TEXT,
  tenant_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_spans_trace_time
  ON spans (trace_id, start_time);
CREATE INDEX IF NOT EXISTS idx_spans_task_time ON spans (task_id, start_time);
CREATE INDEX IF NOT EXISTS idx_spans_tenant_time
  ON spans (tenant_id, start_time);
CREATE INDEX IF NOT EXISTS idx_spans_start_time ON spans (start_time DESC);
CREATE INDEX IF NOT EXISTS idx_spans_attributes
  ON spans USING gin (attributes);

CREATE TABLE IF NOT EXISTS llm_cache (
  cache_key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_expires ON llm_cache (expires_at);

CREATE TABLE IF NOT EXISTS embedding_cache (
  cache_key TEXT PRIMARY KEY,
  vector TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_embedding_cache_expires
  ON embedding_cache (expires_at);

CREATE TABLE IF NOT EXISTS llm_calls (
  call_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  tenant_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
  duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  provider TEXT,
  prompt_version TEXT,
  status TEXT,
  error_code TEXT,
  cache_hit BOOLEAN NOT NULL DEFAULT false,
  fallback_from TEXT,
  attempt INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_task ON llm_calls (task_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_tenant_time
  ON llm_calls (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  status TEXT NOT NULL,
  comment TEXT,
  payload TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_by TEXT,
  decided_at TIMESTAMPTZ,
  external_ref TEXT,
  UNIQUE (task_id, revision)
);
CREATE INDEX IF NOT EXISTS idx_approvals_status_updated
  ON approvals (status, updated_at);
CREATE INDEX IF NOT EXISTS idx_approvals_task ON approvals (task_id);

CREATE TABLE IF NOT EXISTS idempotency (
  key TEXT PRIMARY KEY,
  result TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency (expires_at);

CREATE TABLE IF NOT EXISTS badcases (
  badcase_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  task_id TEXT,
  tenant_id TEXT NOT NULL,
  category TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'medium',
  user_input TEXT NOT NULL DEFAULT '',
  expected TEXT NOT NULL DEFAULT '',
  actual TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  root_cause TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_badcases_status ON badcases (status);
CREATE INDEX IF NOT EXISTS idx_badcases_tenant_time
  ON badcases (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS outbox (
  id BIGSERIAL PRIMARY KEY,
  aggregate_type TEXT NOT NULL,
  aggregate_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  locked_by TEXT,
  locked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
  ON outbox (status, available_at);
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate
  ON outbox (aggregate_type, aggregate_id);

CREATE TABLE IF NOT EXISTS policy_clauses (
  clause_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  doc_id TEXT NOT NULL,
  parent_id TEXT,
  path TEXT NOT NULL,
  clause_type TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  table_id TEXT,
  policy_version TEXT NOT NULL,
  effective_from TEXT,
  effective_to TEXT,
  order_no INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_policy_clauses_tenant_version
  ON policy_clauses (tenant_id, policy_version);
CREATE INDEX IF NOT EXISTS idx_policy_clauses_title_trgm
  ON policy_clauses USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_policy_clauses_text_trgm
  ON policy_clauses USING gin (text gin_trgm_ops);

CREATE TABLE IF NOT EXISTS policy_edges (
  source_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  target_id TEXT NOT NULL,
  PRIMARY KEY (source_id, relation, target_id)
);

CREATE TABLE IF NOT EXISTS policy_tables (
  table_id TEXT PRIMARY KEY,
  source_clause_id TEXT NOT NULL,
  columns_json TEXT NOT NULL,
  rows_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_definitions (
  definition_id TEXT PRIMARY KEY,
  term TEXT NOT NULL,
  text TEXT NOT NULL,
  source_clause_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_ingest_reviews (
  review_id BIGSERIAL PRIMARY KEY,
  clause_id TEXT NOT NULL,
  ref_text TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS policy_ingest_reviews;
DROP TABLE IF EXISTS policy_definitions;
DROP TABLE IF EXISTS policy_tables;
DROP TABLE IF EXISTS policy_edges;
DROP TABLE IF EXISTS policy_clauses;
DROP TABLE IF EXISTS outbox;
DROP TABLE IF EXISTS badcases;
DROP TABLE IF EXISTS idempotency;
DROP TABLE IF EXISTS approvals;
DROP TABLE IF EXISTS llm_calls;
DROP TABLE IF EXISTS embedding_cache;
DROP TABLE IF EXISTS llm_cache;
DROP TABLE IF EXISTS spans;
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS user_memories;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS tasks;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(UPGRADE_SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWNGRADE_SQL)
