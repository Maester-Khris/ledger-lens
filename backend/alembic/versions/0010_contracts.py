"""contracts: extraction runs, per-field routing, human reviews

Revision ID: 0010_contracts
Revises: 0009_retrieval_assistant
"""
from alembic import op

revision = "0010_contracts"
down_revision = "0009_retrieval_assistant"
branch_labels = None
depends_on = None

RECORD_TABLES = ("extraction_runs", "extracted_fields", "field_reviews")


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        "CREATE TYPE field_routing AS ENUM ('accepted', 'needs_review')",
        "CREATE TYPE review_decision AS ENUM ('confirmed', 'corrected', 'rejected')",
        "CREATE TABLE extraction_runs ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " version_id uuid NOT NULL REFERENCES document_versions(id),"
        " schema_version text NOT NULL,"
        " model_id text NOT NULL,"
        " prompt_version text NOT NULL,"
        " temperature numeric(3,2) NOT NULL CHECK (temperature >= 0),"
        " config_hash text NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),"
        " input_hash text NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),"
        " raw_output jsonb NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT clock_timestamp())",
        "CREATE INDEX ix_extraction_runs_version ON extraction_runs (version_id, created_at DESC)",
        "CREATE TABLE extracted_fields ("
        " run_id uuid NOT NULL REFERENCES extraction_runs(id),"
        " field_path text NOT NULL,"
        " value jsonb NOT NULL,"
        " element_ids uuid[] NOT NULL,"
        " quote text NOT NULL,"
        " grounded boolean NOT NULL,"
        " validator_errors text[] NOT NULL,"
        " page_grade text NOT NULL CHECK (page_grade IN ('POOR', 'FAIR', 'GOOD', 'EXCELLENT')),"
        " routing field_routing NOT NULL,"
        " PRIMARY KEY (run_id, field_path),"
        " CONSTRAINT ck_fields_accepted_rule CHECK (routing = 'needs_review' OR"
        "   (grounded AND cardinality(validator_errors) = 0 AND page_grade IN ('GOOD', 'EXCELLENT'))))",
        "CREATE TABLE field_reviews ("
        " run_id uuid NOT NULL,"
        " field_path text NOT NULL,"
        " decision review_decision NOT NULL,"
        " corrected_value jsonb NULL,"
        " decided_by text NOT NULL,"
        " reason text NULL,"
        " decided_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (run_id, field_path),"
        " FOREIGN KEY (run_id, field_path) REFERENCES extracted_fields (run_id, field_path),"
        " CONSTRAINT ck_reviews_corrected_value CHECK ((decision = 'corrected') = (corrected_value IS NOT NULL)))",
    )
    for table in RECORD_TABLES:
        _run(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
            f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        )


def downgrade() -> None:
    _run(
        "DROP TABLE field_reviews",
        "DROP TABLE extracted_fields",
        "DROP TABLE extraction_runs",
        "DROP TYPE review_decision",
        "DROP TYPE field_routing",
    )
