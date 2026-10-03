"""chat turn timing and the usage view (P7)

Revision ID: 0016_chat_turn_timing
Revises: 0015_feedback_descriptions
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0016_chat_turn_timing"
down_revision: Union[str, Sequence[str], None] = "0015_feedback_descriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for statement in (
        # One client-measured TTFB per chat turn. Insert-only, like every other chat table: the unique key on turn_id
        # makes a second write a no-op, and the first value wins (spec P7 section 3).
        "CREATE TABLE chat_turn_timing ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " turn_id uuid NOT NULL UNIQUE REFERENCES chat_turns(id),"
        " guest_id uuid NOT NULL REFERENCES guests(id),"
        " ttfb_ms integer NOT NULL CONSTRAINT ck_chat_turn_timing_range CHECK (ttfb_ms BETWEEN 0 AND 60000),"
        " created_at timestamptz NOT NULL DEFAULT now())",
        "CREATE TRIGGER trg_chat_turn_timing_append_only BEFORE UPDATE OR DELETE ON chat_turn_timing "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
        "CREATE TRIGGER trg_chat_turn_timing_no_truncate BEFORE TRUNCATE ON chat_turn_timing "
        "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        # ledger_app gets SELECT and INSERT from the 0003 default privileges; the demo role needs an explicit grant.
        "GRANT INSERT, SELECT ON chat_turn_timing TO ledger_demo",
        # Cited-answer share and TTFB per day. A session reached a cited answer when any of its turns that day was
        # 'answered' with at least one citation. Averages skip turns that have no timing row.
        """
        CREATE VIEW chat_usage_daily AS
        WITH sessions AS (
          SELECT date_trunc('day', created_at) AS day, session_id,
                 bool_or(outcome = 'answered' AND jsonb_array_length(citations) > 0) AS reached_cited
          FROM chat_turns GROUP BY 1, 2
        ), timing AS (
          SELECT date_trunc('day', t.created_at) AS day, tt.ttfb_ms
          FROM chat_turn_timing tt JOIN chat_turns t ON t.id = tt.turn_id
        )
        SELECT s.day,
               count(*) AS sessions,
               count(*) FILTER (WHERE s.reached_cited) AS cited_sessions,
               round(100.0 * count(*) FILTER (WHERE s.reached_cited) / count(*), 1) AS cited_pct,
               (SELECT count(*) FROM timing ti WHERE ti.day = s.day) AS timed_turns,
               (SELECT round(avg(ti.ttfb_ms)) FROM timing ti WHERE ti.day = s.day) AS avg_ttfb_ms
        FROM sessions s GROUP BY s.day ORDER BY s.day
        """,
        "GRANT SELECT ON chat_usage_daily TO ledger_app",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP VIEW chat_usage_daily")
    op.execute("DROP TABLE chat_turn_timing")
