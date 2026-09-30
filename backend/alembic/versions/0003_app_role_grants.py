"""grant the runtime app role read + insert only

Revision ID: 0003_app_role_grants
Revises: 0002_balance_trigger
"""
from alembic import op

revision = "0003_app_role_grants"
down_revision = "0002_balance_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA public TO ledger_app")
    op.execute("GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO ledger_app")
    # Tables created later by ledger_owner get the same grants automatically.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT ON TABLES TO ledger_app"
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT ON TABLES FROM ledger_app"
    )
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ledger_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM ledger_app")
