"""answer feedback and document descriptions (P5 + P8)

Revision ID: 0015_feedback_descriptions
Revises: 0014_chat_outcome_clarified
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_feedback_descriptions"
down_revision: Union[str, Sequence[str], None] = "0014_chat_outcome_clarified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# One line per demo document, matched by document_key. A database without these documents gets no rows.
DESCRIPTIONS = (
    ("tremblay-ima", "Synthetic household agreement: a graduated advisory fee in CAD, billed quarterly. "
                     "The only contract with billing records to compare against."),
    ("calamos-emerging-market-equity", "Notice amending a fund management agreement: an eight-tier fee on average "
                                       "daily net assets, down to 0.90% above $26 billion."),
    ("aim-global-trends-advisory", "Master advisory agreement from 2001: a four-tier fee starting at 0.975%, with a "
                                   "60-day termination notice."),
    ("nomura-tax-free-colorado-ima", "2025 management agreement for the Nomura Tax-Free Colorado Fund: a four-tier "
                                     "fee starting at 0.55%, paid monthly."),
)


def upgrade() -> None:
    for statement in (
        "CREATE TYPE feedback_rating AS ENUM ('up', 'down')",
        # A guest's opinion of one reply (spec P5). Append-only by privilege: nobody is granted UPDATE or DELETE, and
        # the latest row per guest and turn is the guest's feedback. The API caps a comment at 1000 characters;
        # tokenising can lengthen it, hence the wider limit here.
        "CREATE TABLE chat_feedback ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " turn_id uuid NOT NULL REFERENCES chat_turns(id),"
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " rating feedback_rating NOT NULL,"
        " comment_redacted text NULL CONSTRAINT ck_chat_feedback_comment_length CHECK (char_length(comment_redacted) <= 4000),"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE INDEX ix_chat_feedback_turn ON chat_feedback (turn_id, created_at DESC)",
        # ledger_app gets SELECT and INSERT from 0003's default privileges, ledger_demo SELECT from 0013's.
        "GRANT INSERT ON chat_feedback TO ledger_demo",
        # documents is append-only (its trigger rejects UPDATE), so the one-line description lives beside it (spec D9).
        "CREATE TABLE document_descriptions ("
        " document_id uuid PRIMARY KEY REFERENCES documents(id),"
        " description text NOT NULL CONSTRAINT ck_document_descriptions_length CHECK (char_length(description) BETWEEN 1 AND 200),"
        " created_at timestamptz NOT NULL DEFAULT now())",
    ):
        op.execute(statement)
    insert = sa.text("INSERT INTO document_descriptions (document_id, description) "
                     "SELECT id, :description FROM documents WHERE document_key = :document_key")
    for document_key, description in DESCRIPTIONS:
        op.get_bind().execute(insert, {"document_key": document_key, "description": description})


def downgrade() -> None:
    op.execute("DROP TABLE document_descriptions")
    op.execute("DROP TABLE chat_feedback")
    op.execute("DROP TYPE feedback_rating")
