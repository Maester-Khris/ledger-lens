"""documents: contracts, versions, event log, redacted elements, PII vault

Revision ID: 0008_documents
Revises: 0007_reporting
"""
from alembic import op

revision = "0008_documents"
down_revision = "0007_reporting"
branch_labels = None
depends_on = None

RECORD_TABLES = ("documents", "document_versions", "version_events", "document_elements", "pii_tokens")


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        "CREATE TYPE document_type AS ENUM ('contract')",
        "CREATE TYPE version_stage AS ENUM ('stored', 'parsed', 'indexed', 'extracted', 'failed')",
        "CREATE TYPE element_kind AS ENUM ('heading', 'paragraph', 'table')",
        "CREATE TABLE documents ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " document_key text NOT NULL CHECK (document_key ~ '^[a-z0-9][a-z0-9-]{1,63}$'),"
        " doc_type document_type NOT NULL,"
        " title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),"
        " source_url text NULL,"
        # The billing household an advisory agreement belongs to; lets tools resolve it without
        # the model ever seeing household names. NULL for fund-level (EDGAR) agreements.
        " household_id uuid NULL REFERENCES households(id),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_documents_tenant_key UNIQUE (tenant_id, document_key))",
        "CREATE TABLE document_versions ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " document_id uuid NOT NULL REFERENCES documents(id),"
        " version integer NOT NULL CHECK (version >= 1),"
        " file_sha256 text NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),"
        " mime_type text NOT NULL,"
        " byte_size bigint NOT NULL CHECK (byte_size > 0),"
        " page_count integer NOT NULL CHECK (page_count > 0),"
        " uploaded_by text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_versions_document_version UNIQUE (document_id, version),"
        " CONSTRAINT uq_versions_document_file UNIQUE (document_id, file_sha256))",
        "CREATE TABLE version_events ("
        " id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
        " version_id uuid NOT NULL REFERENCES document_versions(id),"
        " stage version_stage NOT NULL,"
        " detail jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " created_at timestamptz NOT NULL DEFAULT clock_timestamp())",
        "CREATE INDEX ix_version_events_version ON version_events (version_id, id)",
        "CREATE INDEX ix_documents_household ON documents (household_id) WHERE household_id IS NOT NULL",
        "CREATE TABLE document_elements ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " version_id uuid NOT NULL REFERENCES document_versions(id),"
        " ordinal integer NOT NULL CHECK (ordinal >= 0),"
        " kind element_kind NOT NULL,"
        " section_path text[] NOT NULL,"
        " page_start integer NOT NULL CHECK (page_start >= 1),"
        " page_end integer NOT NULL,"
        " text_redacted text NOT NULL CHECK (length(text_redacted) > 0),"
        " parser_version text NOT NULL,"
        " CONSTRAINT uq_elements_version_ordinal UNIQUE (version_id, ordinal),"
        " CONSTRAINT ck_elements_pages CHECK (page_start <= page_end))",
        "CREATE TABLE pii_tokens ("
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " token text NOT NULL CHECK (token ~ '^<[A-Z_]+_[0-9a-f]{12}>$'),"
        " entity_type text NOT NULL,"
        " value_encrypted bytea NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (tenant_id, token))",
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
        "DROP TABLE pii_tokens",
        "DROP TABLE document_elements",
        "DROP TABLE version_events",
        "DROP TABLE document_versions",
        "DROP TABLE documents",
        "DROP TYPE element_kind",
        "DROP TYPE version_stage",
        "DROP TYPE document_type",
    )
