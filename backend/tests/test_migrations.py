from alembic import command

from app import config
from tests.support import alembic_config, reset_schema


def test_migrations_upgrade_downgrade_upgrade():
    url = config.MIGRATION_ROUNDTRIP_DATABASE_URL
    reset_schema(url)
    alembic = alembic_config(url)

    command.upgrade(alembic, "head")
    command.downgrade(alembic, "base")
    command.upgrade(alembic, "head")


def test_chat_turn_timing_append_only():
    import pytest
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import DBAPIError

    url = config.MIGRATION_ROUNDTRIP_DATABASE_URL
    reset_schema(url)
    alembic = alembic_config(url)
    command.upgrade(alembic, "head")

    engine = create_engine(url)
    with engine.begin() as conn:
        tenant_id = conn.execute(text("INSERT INTO tenants (id, name) VALUES (gen_random_uuid(), 'T') RETURNING id")).scalar()
        guest_id = conn.execute(text("INSERT INTO guests (id, tenant_id) VALUES (gen_random_uuid(), :t) RETURNING id"), {"t": tenant_id}).scalar()
        turn_id = conn.execute(text(
            "INSERT INTO chat_turns (id, tenant_id, guest_id, session_id, question_redacted, answer_redacted, citations, retrieved,"
            " outcome, model_id, prompt_version, graph_version, input_tokens, output_tokens, latency_ms)"
            " VALUES (gen_random_uuid(), :t, :g, 's', 'q', 'a', '[]', '[]', 'answered', 'm', 'p', 'v', 0, 0, 1) RETURNING id"),
            {"t": tenant_id, "g": guest_id}).scalar()
        timing_id = conn.execute(text("INSERT INTO chat_turn_timing (id, tenant_id, turn_id, guest_id, ttfb_ms) VALUES (gen_random_uuid(), :t, :turn, :g, 50) RETURNING id"), {"t": tenant_id, "turn": turn_id, "g": guest_id}).scalar()

    # A rejected statement aborts its transaction, so each rejection gets its own transaction.
    for statement, params in (
        ("UPDATE chat_turn_timing SET ttfb_ms = 100 WHERE id = :id", {"id": timing_id}),
        ("DELETE FROM chat_turn_timing WHERE id = :id", {"id": timing_id}),
        ("UPDATE chat_turns SET outcome = 'refused' WHERE id = :id", {"id": turn_id}),
    ):
        with pytest.raises(DBAPIError, match="is append-only"):
            with engine.begin() as conn:
                conn.execute(text(statement), params)
