import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.assistant.models import ChatOutcome, ChatTurn


def test_app_role_can_delete_from_element_search_only(db_session):
    db_session.execute(text("DELETE FROM element_search WHERE false"))  # privilege granted
    db_session.rollback()
    with pytest.raises(ProgrammingError):
        db_session.execute(text("DELETE FROM chat_turns WHERE false"))


def test_chat_turns_are_append_only(db_session, owner_session, tenant_id):
    turn = ChatTurn(tenant_id=tenant_id, session_id="s", question_redacted="q", answer_redacted=None,
                    citations=[], retrieved=[], outcome=ChatOutcome.refused, model_id="m", prompt_version="p",
                    graph_version="g", input_tokens=0, output_tokens=0, latency_ms=1)
    db_session.add(turn)
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        owner_session.execute(text("UPDATE chat_turns SET session_id = 'x' WHERE id = :id"), {"id": turn.id})
    assert exc_info.value.orig.sqlstate == "23001"
