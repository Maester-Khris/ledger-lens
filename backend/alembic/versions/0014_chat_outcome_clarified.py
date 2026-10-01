"""chat outcome 'clarified' (P4): a turn that ended with one clarifying question

Revision ID: 0014_chat_outcome_clarified
Revises: 0013_demo_role_guest_overlays
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014_chat_outcome_clarified"
down_revision: Union[str, Sequence[str], None] = "0013_demo_role_guest_overlays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE chat_outcome ADD VALUE IF NOT EXISTS 'clarified'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum type. Keeping it is harmless: after a code rollback nothing writes it.
    pass
