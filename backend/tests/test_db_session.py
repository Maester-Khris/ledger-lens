import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError


def test_app_session_connects_as_restricted_role(db_session):
    assert db_session.execute(text("SELECT current_user")).scalar_one() == "ledger_app"


def test_app_role_cannot_delete_ledger_rows(db_session):
    with pytest.raises(ProgrammingError) as exc_info:
        db_session.execute(text("DELETE FROM postings"))
    assert exc_info.value.orig.sqlstate == "42501"  # insufficient_privilege


def test_owner_session_connects_as_schema_owner(owner_session):
    assert owner_session.execute(text("SELECT current_user")).scalar_one() == "ledger_owner"
