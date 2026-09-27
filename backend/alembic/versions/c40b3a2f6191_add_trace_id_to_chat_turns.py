"""add trace_id to chat_turns

Revision ID: c40b3a2f6191
Revises: 0010_contracts
Create Date: 2026-09-27 10:55:23.475026

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c40b3a2f6191'
down_revision: Union[str, Sequence[str], None] = '0010_contracts'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chat_turns', sa.Column('trace_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_turns', 'trace_id')
