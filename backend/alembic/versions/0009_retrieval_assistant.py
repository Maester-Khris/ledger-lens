"""retrieval + assistant: derived full-text search table, chat turn audit

Revision ID: 0009_retrieval_assistant
Revises: 0008_documents
"""
from alembic import op

revision = "0009_retrieval_assistant"
down_revision = "0008_documents"
branch_labels = None
depends_on = None


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        # Derived, rebuildable from document_elements. Holds current versions only; the only table
        # the app role may DELETE from (same scoped-grant pattern as UPDATE on accounts in 0004).
        "CREATE TABLE element_search ("
        " element_id uuid PRIMARY KEY REFERENCES document_elements(id),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " document_id uuid NOT NULL REFERENCES documents(id),"
        " version_id uuid NOT NULL REFERENCES document_versions(id),"
        " tsv tsvector NOT NULL)",
        "CREATE INDEX ix_element_search_tsv ON element_search USING GIN (tsv)",
        "CREATE INDEX ix_element_search_tenant_document ON element_search (tenant_id, document_id)",
        "CREATE INDEX ix_element_search_version ON element_search (version_id)",
        "GRANT DELETE ON element_search TO ledger_app",
        "CREATE TYPE chat_outcome AS ENUM ('answered', 'refused', 'timed_out', 'cancelled', 'error')",
        "CREATE TABLE chat_turns ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " session_id text NOT NULL,"
        " question_redacted text NOT NULL,"
        " answer_redacted text NULL,"
        " citations jsonb NOT NULL,"
        " retrieved jsonb NOT NULL,"
        " outcome chat_outcome NOT NULL,"
        " model_id text NOT NULL,"
        " prompt_version text NOT NULL,"
        " graph_version text NOT NULL,"
        " input_tokens integer NOT NULL CHECK (input_tokens >= 0),"
        " output_tokens integer NOT NULL CHECK (output_tokens >= 0),"
        " latency_ms integer NOT NULL CHECK (latency_ms >= 0),"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_chat_turns_tenant_created ON chat_turns (tenant_id, created_at DESC)",
        "CREATE INDEX ix_chat_turns_session_created ON chat_turns (session_id, created_at)",
        "CREATE TRIGGER trg_chat_turns_append_only BEFORE UPDATE OR DELETE ON chat_turns "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        "CREATE TRIGGER trg_chat_turns_no_truncate BEFORE TRUNCATE ON chat_turns "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
    )


def downgrade() -> None:
    _run(
        "DROP TABLE chat_turns",
        "DROP TYPE chat_outcome",
        "REVOKE DELETE ON element_search FROM ledger_app",
        "DROP TABLE element_search",
    )
