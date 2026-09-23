
"""billing: households, valuations, versioned fee schedules, fee calculations

Revision ID: 0005_billing
Revises: 0004_ledger_core
"""
from alembic import op

revision = "0005_billing"
down_revision = "0004_ledger_core"
branch_labels = None
depends_on = None

APPEND_ONLY = (
    "client_accounts",
    "account_valuations",
    "fee_schedule_versions",
    "fee_schedule_tiers",
    "household_fee_assignments",
    "fee_calculations",
)


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        "CREATE EXTENSION IF NOT EXISTS btree_gist",
        "CREATE TYPE fee_method AS ENUM ('graduated', 'cliff')",
        "CREATE TABLE households ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " name text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TABLE clients ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " household_id uuid NOT NULL REFERENCES households(id),"
        " name text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_clients_household ON clients (household_id)",
        "CREATE TABLE client_accounts ("
        " account_id uuid PRIMARY KEY REFERENCES accounts(id),"
        " client_id uuid NOT NULL REFERENCES clients(id),"
        " linked_on date NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_client_accounts_client ON client_accounts (client_id)",
        "CREATE TABLE account_valuations ("
        " account_id uuid NOT NULL REFERENCES accounts(id),"
        " as_of date NOT NULL,"
        " market_value_minor bigint NOT NULL CONSTRAINT ck_account_valuations_non_negative CHECK (market_value_minor >= 0),"
        " source text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (account_id, as_of))",
        "CREATE TABLE fee_schedules ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " name text NOT NULL,"
        " revenue_account_id uuid NOT NULL REFERENCES accounts(id),"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TABLE fee_schedule_versions ("
        " schedule_id uuid NOT NULL REFERENCES fee_schedules(id),"
        " version int NOT NULL CHECK (version > 0),"
        " method fee_method NOT NULL,"
        " valid_during daterange NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (schedule_id, valid_during WITHOUT OVERLAPS),"
        " CONSTRAINT uq_fee_schedule_versions_version UNIQUE (schedule_id, version))",
        "CREATE TABLE fee_schedule_tiers ("
        " schedule_id uuid NOT NULL,"
        " version int NOT NULL,"
        " tier_no int NOT NULL CHECK (tier_no > 0),"
        " up_to_minor bigint NULL CHECK (up_to_minor > 0),"
        " rate_bps numeric(8,4) NOT NULL CHECK (rate_bps >= 0),"
        " PRIMARY KEY (schedule_id, version, tier_no),"
        " FOREIGN KEY (schedule_id, version) REFERENCES fee_schedule_versions (schedule_id, version))",
        "CREATE TABLE household_fee_assignments ("
        " household_id uuid NOT NULL REFERENCES households(id),"
        " schedule_id uuid NOT NULL REFERENCES fee_schedules(id),"
        " valid_during daterange NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (household_id, valid_during WITHOUT OVERLAPS))",
        "CREATE TABLE fee_calculations ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " household_id uuid NOT NULL REFERENCES households(id),"
        " period daterange NOT NULL,"
        " schedule_id uuid NOT NULL,"
        " schedule_version int NOT NULL,"
        " method fee_method NOT NULL,"
        " inputs jsonb NOT NULL,"
        " household_value_minor bigint NOT NULL CHECK (household_value_minor >= 0),"
        " period_fee_minor bigint NOT NULL CHECK (period_fee_minor > 0),"
        " allocations jsonb NOT NULL,"
        " rounding_remainder_minor bigint NOT NULL CHECK (rounding_remainder_minor >= 0),"
        " posting_id uuid NOT NULL REFERENCES postings(id),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_fee_calculations_posting UNIQUE (posting_id),"
        " FOREIGN KEY (schedule_id, schedule_version) REFERENCES fee_schedule_versions (schedule_id, version))",
    )
    for table in APPEND_ONLY:
        _run(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
            f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        )


def downgrade() -> None:
    _run(
        "DROP TABLE fee_calculations",
        "DROP TABLE household_fee_assignments",
        "DROP TABLE fee_schedule_tiers",
        "DROP TABLE fee_schedule_versions",
        "DROP TABLE fee_schedules",
        "DROP TABLE account_valuations",
        "DROP TABLE client_accounts",
        "DROP TABLE clients",
        "DROP TABLE households",
        "DROP TYPE fee_method",
        "DROP EXTENSION IF EXISTS btree_gist",
    )
