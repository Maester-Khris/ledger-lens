"""ledger core: tenants, currencies, fingerprints, append-only facts, posting validity

Revision ID: 0004_ledger_core
Revises: 0003_app_role_grants
"""
from alembic import op

revision = "0004_ledger_core"
down_revision = "0003_app_role_grants"
branch_labels = None
depends_on = None

DEMO_TENANT_ID = "00000000-0000-0000-0000-000000000001"


# Helpers are local on purpose: a migration is a frozen snapshot and must never
# import code that can change after it ships.
def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def _append_only(table: str) -> None:
    _run(
        f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
    )


def _drop_append_only(table: str) -> None:
    _run(
        f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}",
        f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}",
    )


def upgrade() -> None:
    # --- reference data -------------------------------------------------------
    _run(
        "CREATE TABLE currencies ("
        " code text PRIMARY KEY CHECK (code ~ '^[A-Z]{3}$'),"
        " minor_units smallint NOT NULL CHECK (minor_units BETWEEN 0 AND 4))",
        "INSERT INTO currencies (code, minor_units) VALUES ('CAD', 2), ('USD', 2)",
        "CREATE TABLE tenants ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " name text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now())",
        f"INSERT INTO tenants (id, name) VALUES ('{DEMO_TENANT_ID}', 'Demo tenant')",
        "CREATE TYPE normal_balance AS ENUM ('debit', 'credit')",
        "CREATE TYPE posting_source AS ENUM ('api', 'fee_run', 'ai_tool', 'stress_test')",
    )

    # --- accounts ----------------------------------------------------------------
    _run(
        f"ALTER TABLE accounts ADD COLUMN tenant_id uuid NOT NULL DEFAULT '{DEMO_TENANT_ID}' REFERENCES tenants(id)",
        "ALTER TABLE accounts ALTER COLUMN tenant_id DROP DEFAULT",
        "ALTER TABLE accounts ADD CONSTRAINT fk_accounts_currency FOREIGN KEY (currency) REFERENCES currencies(code)",
        "ALTER TABLE accounts ADD COLUMN normal_balance normal_balance NOT NULL DEFAULT 'debit'",
        "ALTER TABLE accounts ALTER COLUMN normal_balance DROP DEFAULT",
        "ALTER TABLE accounts ADD COLUMN gl_code text NULL CONSTRAINT ck_accounts_gl_code_not_blank CHECK (gl_code <> '')",
    )

    # --- postings ----------------------------------------------------------------
    _run(
        f"ALTER TABLE postings ADD COLUMN tenant_id uuid NOT NULL DEFAULT '{DEMO_TENANT_ID}' REFERENCES tenants(id)",
        "ALTER TABLE postings ALTER COLUMN tenant_id DROP DEFAULT",
        "ALTER TABLE postings ADD COLUMN effective_at timestamptz NOT NULL DEFAULT now()",
        "ALTER TABLE postings ADD COLUMN request_fingerprint text",
        # Legacy dev rows were never seen by an API client; fingerprint them by id.
        "UPDATE postings SET request_fingerprint = encode(sha256(id::text::bytea), 'hex')",
        "ALTER TABLE postings ALTER COLUMN request_fingerprint SET NOT NULL",
        "ALTER TABLE postings ADD CONSTRAINT ck_postings_fingerprint_sha256 CHECK (request_fingerprint ~ '^[0-9a-f]{64}$')",
        "ALTER TABLE postings ADD COLUMN source posting_source NOT NULL DEFAULT 'api'",
        "ALTER TABLE postings ALTER COLUMN source DROP DEFAULT",
        "ALTER TABLE postings ADD COLUMN reverses_posting_id uuid NULL REFERENCES postings(id)",
        "ALTER TABLE postings ADD CONSTRAINT uq_postings_reverses_posting_id UNIQUE (reverses_posting_id)",
        "ALTER TABLE postings ADD CONSTRAINT ck_postings_not_self_reversal CHECK (reverses_posting_id <> id)",
        "ALTER TABLE postings DROP CONSTRAINT postings_idempotency_key_key",
        "ALTER TABLE postings ADD CONSTRAINT uq_postings_tenant_idempotency_key UNIQUE (tenant_id, idempotency_key)",
        "ALTER TABLE postings ADD CONSTRAINT ck_postings_idempotency_key_length CHECK (char_length(idempotency_key) BETWEEN 1 AND 255)",
        "CREATE INDEX ix_postings_tenant_created ON postings (tenant_id, created_at DESC, id DESC)",
    )

    # --- replace the insert-only balance trigger ------------------------------------
    _run(
        "DROP TRIGGER trg_check_posting_balance ON entries",
        "DROP FUNCTION check_posting_balance()",
    )

    # --- append-only facts ----------------------------------------------------------
    _run(
        """
        CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION '% is append-only: % is not allowed; record a new fact (reversal or new version) instead',
            TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("currencies", "postings", "entries"):
        _append_only(table)

    _run(
        """
        CREATE FUNCTION guard_account_change() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'accounts cannot be deleted' USING ERRCODE = 'restrict_violation';
          END IF;
          IF NEW.id IS DISTINCT FROM OLD.id
             OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
             OR NEW.currency IS DISTINCT FROM OLD.currency
             OR NEW.normal_balance IS DISTINCT FROM OLD.normal_balance
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'account % : only name and a first gl_code may change', OLD.id
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF OLD.gl_code IS NOT NULL AND NEW.gl_code IS DISTINCT FROM OLD.gl_code THEN
            RAISE EXCEPTION 'account % : gl_code can be set once and never changed', OLD.id
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """,
        "CREATE TRIGGER trg_accounts_guard BEFORE UPDATE OR DELETE ON accounts "
        "FOR EACH ROW EXECUTE FUNCTION guard_account_change()",
        "CREATE TRIGGER trg_accounts_no_truncate BEFORE TRUNCATE ON accounts "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        "GRANT UPDATE (name, gl_code) ON accounts TO ledger_app",
    )

    # --- posting validity, checked at commit ----------------------------------------------
    _run(
        """
        CREATE FUNCTION assert_posting_valid(p_id uuid) RETURNS void AS $$
        DECLARE
          v_tenant uuid;
          v_reverses uuid;
        BEGIN
          SELECT tenant_id, reverses_posting_id INTO v_tenant, v_reverses
            FROM postings WHERE id = p_id;

          IF NOT EXISTS (SELECT 1 FROM entries WHERE posting_id = p_id AND direction = 'debit')
             OR NOT EXISTS (SELECT 1 FROM entries WHERE posting_id = p_id AND direction = 'credit') THEN
            RAISE EXCEPTION 'posting % needs at least one debit and one credit entry', p_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF EXISTS (
            SELECT 1
              FROM entries e JOIN accounts a ON a.id = e.account_id
             WHERE e.posting_id = p_id
             GROUP BY a.currency
            HAVING SUM(CASE WHEN e.direction = 'debit' THEN e.amount ELSE -e.amount END) <> 0
          ) THEN
            RAISE EXCEPTION 'posting % does not balance per currency', p_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF EXISTS (
            SELECT 1 FROM entries e JOIN accounts a ON a.id = e.account_id
             WHERE e.posting_id = p_id AND a.tenant_id <> v_tenant
          ) THEN
            RAISE EXCEPTION 'posting % touches an account of another tenant', p_id
              USING ERRCODE = 'check_violation';
          END IF;

          IF v_reverses IS NOT NULL AND EXISTS (
            (SELECT account_id,
                    CASE direction WHEN 'debit' THEN 'credit'::entry_direction ELSE 'debit'::entry_direction END,
                    amount
               FROM entries WHERE posting_id = v_reverses
             EXCEPT ALL
             SELECT account_id, direction, amount FROM entries WHERE posting_id = p_id)
            UNION ALL
            (SELECT account_id, direction, amount FROM entries WHERE posting_id = p_id
             EXCEPT ALL
             SELECT account_id,
                    CASE direction WHEN 'debit' THEN 'credit'::entry_direction ELSE 'debit'::entry_direction END,
                    amount
               FROM entries WHERE posting_id = v_reverses)
          ) THEN
            RAISE EXCEPTION 'posting % must exactly mirror the posting it reverses (%)', p_id, v_reverses
              USING ERRCODE = 'check_violation';
          END IF;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION check_posting_from_posting() RETURNS trigger AS $$
        BEGIN
          PERFORM assert_posting_valid(NEW.id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """,
        """
        CREATE FUNCTION check_posting_from_entry() RETURNS trigger AS $$
        BEGIN
          PERFORM assert_posting_valid(NEW.posting_id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """,
        # On postings too: a posting with zero entries never fires an entries trigger.
        "CREATE CONSTRAINT TRIGGER trg_postings_valid AFTER INSERT ON postings "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_posting_from_posting()",
        "CREATE CONSTRAINT TRIGGER trg_entries_valid AFTER INSERT ON entries "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_posting_from_entry()",
    )


def downgrade() -> None:
    _run(
        "DROP TRIGGER IF EXISTS trg_entries_valid ON entries",
        "DROP TRIGGER IF EXISTS trg_postings_valid ON postings",
        "DROP FUNCTION IF EXISTS check_posting_from_entry()",
        "DROP FUNCTION IF EXISTS check_posting_from_posting()",
        "DROP FUNCTION IF EXISTS assert_posting_valid(uuid)",
        "REVOKE UPDATE ON accounts FROM ledger_app",
        "DROP TRIGGER IF EXISTS trg_accounts_no_truncate ON accounts",
        "DROP TRIGGER IF EXISTS trg_accounts_guard ON accounts",
        "DROP FUNCTION IF EXISTS guard_account_change()",
    )
    for table in ("entries", "postings", "currencies"):
        _drop_append_only(table)
    _run(
        "DROP FUNCTION IF EXISTS forbid_mutation()",
        "DROP INDEX IF EXISTS ix_postings_tenant_created",
        "ALTER TABLE postings DROP CONSTRAINT uq_postings_tenant_idempotency_key",
        "ALTER TABLE postings ADD CONSTRAINT postings_idempotency_key_key UNIQUE (idempotency_key)",
        "ALTER TABLE postings DROP CONSTRAINT ck_postings_idempotency_key_length",
        "ALTER TABLE postings DROP CONSTRAINT ck_postings_not_self_reversal",
        "ALTER TABLE postings DROP CONSTRAINT uq_postings_reverses_posting_id",
        "ALTER TABLE postings DROP COLUMN reverses_posting_id",
        "ALTER TABLE postings DROP COLUMN source",
        "ALTER TABLE postings DROP COLUMN request_fingerprint",
        "ALTER TABLE postings DROP COLUMN effective_at",
        "ALTER TABLE postings DROP COLUMN tenant_id",
        "ALTER TABLE accounts DROP COLUMN gl_code",
        "ALTER TABLE accounts DROP COLUMN normal_balance",
        "ALTER TABLE accounts DROP CONSTRAINT fk_accounts_currency",
        "ALTER TABLE accounts DROP COLUMN tenant_id",
        "DROP TYPE posting_source",
        "DROP TYPE normal_balance",
        "DROP TABLE tenants",
        "DROP TABLE currencies",
        # restore migration 0002's insert-only balance trigger exactly
        """
        CREATE FUNCTION check_posting_balance() RETURNS trigger AS $$
        DECLARE
          imbalance bigint;
        BEGIN
          SELECT COALESCE(
            SUM(CASE WHEN direction = 'debit' THEN amount ELSE -amount END), 0
          )
            INTO imbalance
            FROM entries
            WHERE posting_id = NEW.posting_id;

          IF imbalance != 0 THEN
            RAISE EXCEPTION 'posting % is unbalanced: debit/credit mismatch of %',
              NEW.posting_id, imbalance
              USING ERRCODE = 'integrity_constraint_violation';
          END IF;

          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """,
        "CREATE CONSTRAINT TRIGGER trg_check_posting_balance AFTER INSERT ON entries "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION check_posting_balance()",
    )
