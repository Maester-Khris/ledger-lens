"""balance invariant trigger

Revision ID: 0002_balance_trigger
Revises: 0001_create_ledger_tables
"""
from alembic import op

revision = "0002_balance_trigger"
down_revision = "0001_create_ledger_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
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
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_check_posting_balance
          AFTER INSERT ON entries
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW
          EXECUTE FUNCTION check_posting_balance();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_check_posting_balance ON entries")
    op.execute("DROP FUNCTION IF EXISTS check_posting_balance()")
