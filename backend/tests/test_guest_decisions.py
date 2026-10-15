import dataclasses
import uuid

import pytest
from sqlalchemy import func, select

from app.assistant import dao as assistant_dao
from app.demo import GUEST_DECIDED_BY
from app.governance.dao import (InvocationRecord, count_pending, decide, invocations_for_document, list_invocations,
                                record_invocation)
from app.governance.errors import AlreadyDecided, InvocationNotFound
from app.governance.models import ToolInvocationDecision
from app.governance.types import ToolDecision
from app.ledger.dao import EntryInput, PostingRequest, check_posting
from app.ledger.errors import PostingInvalid
from app.ledger.models import Posting
from app.ledger.types import Direction
from tests.test_governance import MODEL, accounts  # noqa: F401  (accounts is a fixture)

DOCUMENT = uuid.uuid4()


def _guest(db_session, tenant_id):
    return assistant_dao.register_guest(db_session, tenant_id, None)


def _propose(db_session, tenant_id, accounts, guest, *, amount=40_000, credit_amount=None):
    receivable, income = accounts
    return record_invocation(db_session, InvocationRecord(
        tenant_id=tenant_id, session_id="ses_demo", tool_name="compare_contract_to_billing", tool_version="1.0.0",
        model=MODEL, input={"document_id": str(DOCUMENT), "guest_id": str(guest)},
        result_amount_minor=amount, result_currency="CAD",
        proposed_entries=(EntryInput(receivable.id, Direction.debit, amount),
                          EntryInput(income.id, Direction.credit, amount if credit_amount is None else credit_amount)),
    ))


def _postings(db_session, tenant_id) -> int:
    return db_session.scalar(select(func.count()).select_from(Posting).where(Posting.tenant_id == tenant_id))


def _decide(db_session, tenant_id, invocation, decision, guest):
    return decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=decision,
                  decided_by="guest:x", reason=None, overlay_guest=guest)


def test_check_posting_runs_the_ledger_validation_without_writing(db_session, tenant_id, accounts):
    receivable, income = accounts
    balanced = PostingRequest(tenant_id=tenant_id, idempotency_key="check-1", entries=(
        EntryInput(receivable.id, Direction.debit, 500), EntryInput(income.id, Direction.credit, 500)))
    check_posting(db_session, balanced)
    unbalanced = dataclasses.replace(balanced, entries=(
        EntryInput(receivable.id, Direction.debit, 500), EntryInput(income.id, Direction.credit, 400)))
    with pytest.raises(PostingInvalid, match="balance"):
        check_posting(db_session, unbalanced)
    assert _postings(db_session, tenant_id) == 0


def test_a_guest_approval_is_checked_and_kept_for_that_guest_only(db_session, tenant_id, accounts):
    a = _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a)
    assert count_pending(db_session, tenant_id, overlay_guest=a) == 1

    decision = _decide(db_session, tenant_id, invocation, ToolDecision.approved, a)
    assert (decision.recorded, decision.posting_id, decision.decided_by) == (False, None, GUEST_DECIDED_BY)
    assert _postings(db_session, tenant_id) == 0
    assert db_session.get(ToolInvocationDecision, invocation.id) is None
    [(_, seen)] = list_invocations(db_session, tenant_id=tenant_id, overlay_guest=a)
    assert seen.decision is ToolDecision.approved
    assert count_pending(db_session, tenant_id, overlay_guest=a) == 0
    [(_, real)] = list_invocations(db_session, tenant_id=tenant_id)
    assert real is None  # the real decision table is untouched
    assert [(i.id, d.decision) for i, d in invocations_for_document(db_session, tenant_id, DOCUMENT, overlay_guest=a)] == [
        (invocation.id, ToolDecision.approved)]


def test_a_guest_cannot_see_or_decide_another_guests_proposal(db_session, tenant_id, accounts):
    a, b = _guest(db_session, tenant_id), _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a)
    with pytest.raises(InvocationNotFound):
        _decide(db_session, tenant_id, invocation, ToolDecision.approved, b)
    assert list_invocations(db_session, tenant_id=tenant_id, overlay_guest=b) == []
    assert invocations_for_document(db_session, tenant_id, DOCUMENT, overlay_guest=b) == []
    assert count_pending(db_session, tenant_id, overlay_guest=b) == 0


def test_an_invalid_proposal_is_refused_and_leaves_no_decision(db_session, tenant_id, accounts):
    a = _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a, credit_amount=39_999)
    with pytest.raises(PostingInvalid):
        _decide(db_session, tenant_id, invocation, ToolDecision.approved, a)
    [(_, decision)] = list_invocations(db_session, tenant_id=tenant_id, overlay_guest=a)
    assert decision is None


def test_guest_decisions_are_final(db_session, tenant_id, accounts):
    a = _guest(db_session, tenant_id)
    invocation = _propose(db_session, tenant_id, accounts, a)
    _decide(db_session, tenant_id, invocation, ToolDecision.rejected, a)
    with pytest.raises(AlreadyDecided):
        _decide(db_session, tenant_id, invocation, ToolDecision.approved, a)
