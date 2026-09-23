import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.governance.dao import InvocationRecord, ModelConfig, decide, list_invocations, record_invocation
from app.governance.errors import AlreadyDecided, InvocationNotFound, NotCritical
from app.governance.models import ToolInvocationDecision
from app.governance.types import ToolDecision
from app.ledger.dao import EntryInput, get_posting
from app.ledger.errors import PostingInvalid
from app.ledger.types import Direction, NormalBalance, PostingSource
from tests.support import make_account

MODEL = ModelConfig(provider="openai", model_id="gpt-4o-2024-08-06", prompt_version="tax-qa-v3", temperature=Decimal("0.20"))


@pytest.fixture()
def accounts(db_session, tenant_id):
    receivable = make_account(db_session, tenant_id, normal_balance=NormalBalance.debit, name="Employment Income Receivable")
    income = make_account(db_session, tenant_id, normal_balance=NormalBalance.credit, name="Reported Income")
    return receivable, income


def _record(db_session, tenant_id, accounts, *, critical=True, amount=9_450_000):
    receivable, income = accounts
    proposed = (
        (EntryInput(receivable.id, Direction.debit, amount), EntryInput(income.id, Direction.credit, amount))
        if critical else None
    )
    return record_invocation(
        db_session,
        InvocationRecord(
            tenant_id=tenant_id,
            session_id="ses_5d21",
            tool_name="total_reported_income",
            tool_version="1.0.0",
            model=MODEL,
            input={"document_id": "doc_7f3a21c9"},
            result_amount_minor=amount,
            result_currency="CAD",
            citation={"document_id": "doc_7f3a21c9", "page": 1, "section": "Employment income"},
            proposed_entries=proposed,
        ),
    )


def test_recording_a_critical_invocation_pins_the_ai_configuration(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    assert invocation.approval_required is True
    assert (invocation.model_id, invocation.prompt_version, invocation.temperature) == ("gpt-4o-2024-08-06", "tax-qa-v3", Decimal("0.20"))
    assert len(invocation.input_hash) == 64
    assert invocation.proposed_entries[0]["amount"] == 9_450_000


def test_approval_posts_exactly_the_proposed_entries(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    decision = decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id,
                      decision=ToolDecision.approved, decided_by="demo_user", reason="matches T4 box 14")
    posting = get_posting(db_session, tenant_id=tenant_id, posting_id=decision.posting_id)
    assert posting.source is PostingSource.ai_tool
    assert posting.idempotency_key == f"ai:{invocation.id}"
    receivable, income = accounts
    assert {(e.account_id, e.direction, e.amount) for e in posting.entries} == {
        (receivable.id, Direction.debit, 9_450_000), (income.id, Direction.credit, 9_450_000),
    }


def test_rejection_records_a_decision_without_posting(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    decision = decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id,
                      decision=ToolDecision.rejected, decided_by="demo_user", reason="wrong document")
    assert decision.posting_id is None


def test_an_invocation_is_decided_only_once(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.rejected, decided_by="demo_user", reason=None)
    with pytest.raises(AlreadyDecided):
        decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)


def test_non_critical_invocations_take_no_decision(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts, critical=False)
    with pytest.raises(NotCritical):
        decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)


def test_unknown_invocation_is_not_found(db_session, tenant_id):
    with pytest.raises(InvocationNotFound):
        decide(db_session, tenant_id=tenant_id, invocation_id=uuid.uuid4(), decision=ToolDecision.approved, decided_by="demo_user", reason=None)


def test_invalid_proposal_fails_approval_atomically(db_session, tenant_id, accounts):
    receivable, income = accounts
    invocation = record_invocation(
        db_session,
        InvocationRecord(
            tenant_id=tenant_id, session_id="s", tool_name="t", tool_version="1", model=MODEL, input={"document_id": "d"},
            proposed_entries=(EntryInput(receivable.id, Direction.debit, 10), EntryInput(income.id, Direction.credit, 9)),
        ),
    )
    with pytest.raises(PostingInvalid):
        decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)
    assert db_session.get(ToolInvocationDecision, invocation.id) is None


def test_database_rejects_decisions_on_non_critical_invocations(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts, critical=False)
    with pytest.raises(IntegrityError) as exc_info:  # composite FK finds no (id, true) row
        db_session.execute(
            text("INSERT INTO tool_invocation_decisions (invocation_id, decision, decided_by) VALUES (:id, 'rejected', 'x')"),
            {"id": invocation.id},
        )
    assert exc_info.value.orig.sqlstate == "23503"


def test_database_rejects_approval_without_posting(db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(
            text("INSERT INTO tool_invocation_decisions (invocation_id, decision, decided_by) VALUES (:id, 'approved', 'x')"),
            {"id": invocation.id},
        )
    assert exc_info.value.orig.sqlstate == "23514"


def test_list_filters_pending_and_by_posting(db_session, tenant_id, accounts):
    pending = _record(db_session, tenant_id, accounts)
    approved = _record(db_session, tenant_id, accounts)
    decision = decide(db_session, tenant_id=tenant_id, invocation_id=approved.id, decision=ToolDecision.approved, decided_by="demo_user", reason=None)
    assert [inv.id for inv, _ in list_invocations(db_session, tenant_id=tenant_id, pending=True)] == [pending.id]
    by_posting = list_invocations(db_session, tenant_id=tenant_id, posting_id=decision.posting_id)
    assert [(inv.id, d.decision) for inv, d in by_posting] == [(approved.id, ToolDecision.approved)]


# --- API -------------------------------------------------------------------------------------

def test_decision_endpoint_and_listing(client, db_session, tenant_id, accounts):
    invocation = _record(db_session, tenant_id, accounts)
    pending = client.get("/tool-invocations", params={"pending": "true"}).json()
    assert [row["id"] for row in pending] == [str(invocation.id)]

    created = client.post(f"/tool-invocations/{invocation.id}/decision", json={"decision": "approved", "reason": "ok"})
    assert created.status_code == 201
    posting_id = created.json()["posting_id"]
    provenance = client.get("/tool-invocations", params={"posting_id": posting_id}).json()
    assert provenance[0]["model_id"] == "gpt-4o-2024-08-06"
    assert provenance[0]["decision"]["decided_by"] == "demo_user"

    again = client.post(f"/tool-invocations/{invocation.id}/decision", json={"decision": "approved"})
    assert again.status_code == 409 and again.json()["type"] == "/problems/already-decided"


def test_decision_endpoint_errors(client, db_session, tenant_id, accounts):
    lookup = _record(db_session, tenant_id, accounts, critical=False)
    assert client.post(f"/tool-invocations/{lookup.id}/decision", json={"decision": "approved"}).status_code == 422
    assert client.post(f"/tool-invocations/{uuid.uuid4()}/decision", json={"decision": "approved"}).status_code == 404