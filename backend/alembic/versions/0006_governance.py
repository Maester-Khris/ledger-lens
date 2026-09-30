"""governance: AI tool invocations and human approval decisions

Revision ID: 0006_governance
Revises: 0005_billing
"""
from alembic import op

revision = "0006_governance"
down_revision = "0005_billing"
branch_labels = None
depends_on = None


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        "CREATE TYPE tool_decision AS ENUM ('approved', 'rejected')",
        "CREATE TABLE tool_invocations ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " session_id text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " tool_name text NOT NULL,"
        " tool_version text NOT NULL,"
        " model_provider text NOT NULL,"
        " model_id text NOT NULL,"
        " prompt_version text NOT NULL,"
        " temperature numeric(3,2) NOT NULL CHECK (temperature >= 0),"
        " input jsonb NOT NULL,"
        " input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),"
        " result_amount_minor bigint NULL,"
        " result_currency text NULL REFERENCES currencies(code),"
        " citation jsonb NULL,"
        " proposed_entries jsonb NULL,"
        " approval_required boolean NOT NULL,"
        " CONSTRAINT ck_tool_invocations_approval_iff_proposal CHECK (approval_required = (proposed_entries IS NOT NULL)),"
        " CONSTRAINT ck_tool_invocations_currency_with_amount CHECK ((result_amount_minor IS NULL) = (result_currency IS NULL)),"
        " CONSTRAINT uq_tool_invocations_id_approval UNIQUE (id, approval_required))",
        "CREATE INDEX ix_tool_invocations_tenant_created ON tool_invocations (tenant_id, created_at DESC)",
        "CREATE TABLE tool_invocation_decisions ("
        " invocation_id uuid PRIMARY KEY,"
        " approval_required boolean NOT NULL DEFAULT true CONSTRAINT ck_decisions_only_for_critical CHECK (approval_required),"
        " decision tool_decision NOT NULL,"
        " decided_by text NOT NULL,"
        " reason text NULL,"
        " decided_at timestamptz NOT NULL DEFAULT now(),"
        " posting_id uuid NULL REFERENCES postings(id),"
        " CONSTRAINT uq_decisions_posting UNIQUE (posting_id),"
        " CONSTRAINT fk_decisions_critical_invocation FOREIGN KEY (invocation_id, approval_required)"
        "   REFERENCES tool_invocations (id, approval_required),"
        " CONSTRAINT ck_decisions_approved_iff_posting CHECK ((decision = 'approved') = (posting_id IS NOT NULL)))",
    )
    for table in ("tool_invocations", "tool_invocation_decisions"):
        _run(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
            f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        )


def downgrade() -> None:
    _run(
        "DROP TABLE tool_invocation_decisions",
        "DROP TABLE tool_invocations",
        "DROP TYPE tool_decision",
    )