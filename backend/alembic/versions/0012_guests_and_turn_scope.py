"""guests, and the guest and document scope of a chat turn

Revision ID: 0012_guests_and_turn_scope
Revises: 0011_chat_trace_id
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0012_guests_and_turn_scope"
down_revision: Union[str, Sequence[str], None] = "0011_chat_trace_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # SELECT, INSERT come from the default privileges (0003). Attribution needs one updatable column, nothing else.
    op.execute("GRANT UPDATE (last_seen_at) ON guests TO ledger_app")
    op.add_column("chat_turns", sa.Column("guest_id", UUID(as_uuid=True), sa.ForeignKey("guests.id"), nullable=True))
    op.add_column("chat_turns", sa.Column("document_id", UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_turns", "document_id")
    op.drop_column("chat_turns", "guest_id")
    op.drop_table("guests")
