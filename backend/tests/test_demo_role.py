import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app import config
from app.ledger.db import make_session_factory

SHARED = (
    "documents", "document_versions", "document_elements", "pii_tokens", "extraction_runs", "extracted_fields",
    "field_reviews", "postings", "entries", "accounts", "tool_invocation_decisions", "fee_calculations", "gl_exports",
)
OVERLAYS = ("guest_field_reviews", "guest_tool_decisions")


@pytest.fixture(scope="module")
def demo_factory(migrated_test_database):
    return make_session_factory(config.TEST_DEMO_DATABASE_URL)


@pytest.fixture()
def demo_session(demo_factory):
    session = demo_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _can(session, role: str, table: str, privilege: str) -> bool:
    return session.scalar(text("SELECT has_table_privilege(:r, :t, :p)"), {"r": role, "t": table, "p": privilege})


@pytest.mark.parametrize("table", SHARED)
def test_demo_role_cannot_insert_into_shared_tables(demo_session, table):
    with pytest.raises(ProgrammingError) as caught:
        demo_session.execute(text(f"INSERT INTO {table} DEFAULT VALUES"))
    assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege)


def test_demo_role_reads_everything_and_writes_only_chat_state_and_the_overlays(owner_session):
    for table in SHARED + ("guests", "chat_turns", "tool_invocations") + OVERLAYS:
        assert _can(owner_session, "ledger_demo", table, "SELECT"), table
    for table in ("guests", "chat_turns", "tool_invocations") + OVERLAYS:
        assert _can(owner_session, "ledger_demo", table, "INSERT"), table
    for table in OVERLAYS:
        assert _can(owner_session, "ledger_demo", table, "DELETE"), table
        assert not _can(owner_session, "ledger_demo", table, "UPDATE"), table  # decisions are final
    for table in SHARED + ("guests",):
        assert not _can(owner_session, "ledger_demo", table, "DELETE"), table
    column = "SELECT has_column_privilege('ledger_demo', 'guests', :c, 'UPDATE')"
    assert owner_session.scalar(text(column), {"c": "last_seen_at"})
    assert not owner_session.scalar(text(column), {"c": "tenant_id"})


def test_app_role_may_purge_the_overlays(owner_session):
    for table in OVERLAYS:
        assert _can(owner_session, "ledger_app", table, "DELETE"), table


def test_feedback_is_insert_only_and_descriptions_are_read_only_for_the_demo_role(owner_session):
    assert _can(owner_session, "ledger_demo", "chat_feedback", "SELECT")
    assert _can(owner_session, "ledger_demo", "chat_feedback", "INSERT")
    for role in ("ledger_demo", "ledger_app"):
        for privilege in ("UPDATE", "DELETE"):
            assert not _can(owner_session, role, "chat_feedback", privilege), (role, privilege)
    assert _can(owner_session, "ledger_demo", "document_descriptions", "SELECT")
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert not _can(owner_session, "ledger_demo", "document_descriptions", privilege), privilege
