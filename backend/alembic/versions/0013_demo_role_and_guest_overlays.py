"""demo role grants and the per-guest decision overlays

Revision ID: 0013_demo_role_guest_overlays
Revises: 0012_guests_and_turn_scope
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013_demo_role_guest_overlays"
down_revision: Union[str, Sequence[str], None] = "0012_guests_and_turn_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OVERLAYS = "guest_field_reviews, guest_tool_decisions"


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        # A demo guest's decisions (spec P2+P9): same rules as the real tables, keyed by guest, never shared.
        # No append-only triggers: the rows are disposable (24-hour purge). Finality comes from the primary keys
        # and from the demo role having no UPDATE.
        "CREATE TABLE guest_field_reviews ("
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " run_id uuid NOT NULL,"
        " field_path text NOT NULL,"
        " decision review_decision NOT NULL,"
        " corrected_value jsonb NULL,"
        " reason text NULL,"
        " decided_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (guest_id, run_id, field_path),"
        " FOREIGN KEY (run_id, field_path) REFERENCES extracted_fields (run_id, field_path),"
        " CONSTRAINT ck_guest_reviews_corrected_value CHECK ((decision = 'corrected') = (corrected_value IS NOT NULL)))",
        "CREATE TABLE guest_tool_decisions ("
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " invocation_id uuid NOT NULL,"
        " approval_required boolean NOT NULL DEFAULT true CONSTRAINT ck_guest_decisions_only_for_critical CHECK (approval_required),"
        " decision tool_decision NOT NULL,"
        " reason text NULL,"
        " decided_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (guest_id, invocation_id),"
        " CONSTRAINT fk_guest_decisions_critical_invocation FOREIGN KEY (invocation_id, approval_required)"
        "   REFERENCES tool_invocations (id, approval_required))",
        # ledger_app (non-demo API): SELECT and INSERT come from 0003's default privileges; DELETE is for the purge.
        f"GRANT DELETE ON {OVERLAYS} TO ledger_app",
        # ledger_demo (the public demo's API role): read everything, write only chat state and the overlays.
        # The role is created outside migrations (scripts/db_up.sh locally, by hand on Railway): a migration cannot
        # carry a password and ledger_owner cannot create roles. A missing role makes these GRANTs fail, on purpose.
        "GRANT USAGE ON SCHEMA public TO ledger_demo",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO ledger_demo",
        # Later tables are readable too. A later table the demo must WRITE needs its own explicit GRANT INSERT.
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO ledger_demo",
        "GRANT INSERT ON guests, chat_turns, tool_invocations TO ledger_demo",
        "GRANT UPDATE (last_seen_at) ON guests TO ledger_demo",
        f"GRANT INSERT, DELETE ON {OVERLAYS} TO ledger_demo",
    )


def downgrade() -> None:
    _run(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM ledger_demo",
        "REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ledger_demo",
        "REVOKE USAGE ON SCHEMA public FROM ledger_demo",
        "DROP TABLE guest_tool_decisions",
        "DROP TABLE guest_field_reviews",
    )
