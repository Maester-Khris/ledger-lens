"""X1 extraction verification: element boxes, field verifications, field labels, the verified stage

Revision ID: 0017_x1_verification
Revises: 0016_chat_turn_timing
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0017_x1_verification"
down_revision: Union[str, Sequence[str], None] = "0016_chat_turn_timing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECORD_TABLES = ("element_boxes", "field_verifications", "field_labels")


def upgrade() -> None:
    for statement in (
        # Allowed in a transaction since Postgres 12; the value is only used by later transactions.
        "ALTER TYPE version_stage ADD VALUE IF NOT EXISTS 'verified'",
        "CREATE TYPE verification_layer AS ENUM ('ocr_local', 'vision')",
        "CREATE TYPE crop_kind AS ENUM ('element', 'table', 'page')",
        "CREATE TYPE verification_outcome AS ENUM ('agree', 'disagree', 'unreadable', 'error')",
        # Derived from the source PDF (Docling provenance), rebuilt by re-parsing; one row per element.
        "CREATE TABLE element_boxes ("
        " element_id uuid PRIMARY KEY REFERENCES document_elements(id),"
        " boxes jsonb NOT NULL CHECK (jsonb_typeof(boxes) = 'array'))",
        # One row per independent check. The unique key is the check's identity, so a re-run of the stage is a no-op.
        "CREATE TABLE field_verifications ("
        " id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
        " run_id uuid NOT NULL REFERENCES extraction_runs(id),"
        " field_path text NOT NULL,"
        " layer verification_layer NOT NULL,"
        " verifier text NOT NULL,"
        " crop_kind crop_kind NOT NULL,"
        " read_value jsonb NULL,"  # tokenised where it holds personal data
        " outcome verification_outcome NOT NULL,"
        " detail text NULL,"
        " input_tokens integer NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),"
        " output_tokens integer NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),"
        " cost_usd numeric(10,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),"
        " latency_ms integer NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),"
        " created_at timestamptz NOT NULL DEFAULT clock_timestamp(),"
        " CONSTRAINT uq_field_verifications_check UNIQUE (run_id, field_path, layer, verifier, crop_kind))",
        # Measurement, not operations: kept apart from field_reviews. Blind labels never saw the extracted value.
        "CREATE TABLE field_labels ("
        " run_id uuid NOT NULL REFERENCES extraction_runs(id),"
        " field_path text NOT NULL,"
        " labeller text NOT NULL CHECK (labeller ~ '^(human:.+|judge:.+|adjudicated)$'),"
        " label_value jsonb NOT NULL,"
        " blind boolean NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (run_id, field_path, labeller))",
    ):
        op.execute(statement)
    # ledger_app (SELECT, INSERT) and ledger_demo (SELECT) get these tables from the 0003 and 0013 default privileges.
    for table in RECORD_TABLES:
        op.execute(f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()")
        op.execute(f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
                   "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()")


def downgrade() -> None:
    for statement in (
        "DROP TABLE field_labels",
        "DROP TABLE field_verifications",
        "DROP TABLE element_boxes",
        "DROP TYPE verification_outcome",
        "DROP TYPE crop_kind",
        "DROP TYPE verification_layer",
        # The 'verified' value stays on version_stage: Postgres cannot drop an enum value. Rows using it are
        # version_events, which the downgrade of this revision does not touch.
    ):
        op.execute(statement)
