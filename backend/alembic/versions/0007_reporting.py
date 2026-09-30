"""reporting: reproducible GL export records

Revision ID: 0007_reporting
Revises: 0006_governance
"""
from alembic import op

revision = "0007_reporting"
down_revision = "0006_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "CREATE TABLE gl_exports ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " period daterange NOT NULL,"
        " currency text NOT NULL REFERENCES currencies(code),"
        " cutoff timestamptz NOT NULL,"
        " line_count int NOT NULL CHECK (line_count >= 0),"
        " total_debits_minor bigint NOT NULL CHECK (total_debits_minor >= 0),"
        " total_credits_minor bigint NOT NULL,"
        " content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT ck_gl_exports_balanced CHECK (total_debits_minor = total_credits_minor))",
        "CREATE TRIGGER trg_gl_exports_append_only BEFORE UPDATE OR DELETE ON gl_exports "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        "CREATE TRIGGER trg_gl_exports_no_truncate BEFORE TRUNCATE ON gl_exports "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE gl_exports")