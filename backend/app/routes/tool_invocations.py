import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import config
from app.deps import decided_by, get_guest_id, get_overlay_guest, get_session, get_tenant_id, require_overlay_guest
from app.governance.dao import Decision, decide, list_invocations
from app.governance.models import ToolInvocation
from app.governance.types import ToolDecision
from app.ledger.dao import account_labels
from app.assistant import dao as assistant_dao
from app.documents import dao as documents_dao
from app.retrieval import dao as retrieval_dao
from app.reporting.dashboard import invalidate_dashboard_stats

router = APIRouter(prefix="/tool-invocations", tags=["governance"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: ToolDecision
    reason: str | None = Field(default=None, max_length=1000)


class DecisionOut(BaseModel):
    invocation_id: uuid.UUID
    decision: ToolDecision
    decided_by: str
    reason: str | None
    decided_at: datetime
    posting_id: uuid.UUID | None
    recorded: bool


class SourceOut(BaseModel):
    element_id: str
    page: int
    section: str
    quote: str


class InvocationOut(BaseModel):
    id: uuid.UUID
    session_id: str
    trace_id: str | None = None
    created_at: datetime
    tool_name: str
    tool_version: str
    model_provider: str
    model_id: str
    prompt_version: str
    temperature: Decimal
    input: dict
    result_amount_minor: int | None
    result_currency: str | None
    citation: dict | None
    proposed_entries: list | None
    approval_required: bool
    decision: DecisionOut | None
    # Proposals only (N8 S8): the contract and the clauses behind the amount, so an approver sees them on the card.
    document_title: str | None = None
    document_version: int | None = None
    sources: list[SourceOut] = []



def _labelled(session: Session, entries: list | None) -> list | None:
    if entries is None:
        return None
    labels = account_labels(session, (uuid.UUID(e["account_id"]) for e in entries))
    return [
        e | {"account_name": labels[uuid.UUID(e["account_id"])].name, "currency": labels[uuid.UUID(e["account_id"])].currency}
        for e in entries
    ]


def _decision_out(decision: Decision) -> DecisionOut:
    return DecisionOut(
        invocation_id=decision.invocation_id, decision=decision.decision, decided_by=decision.decided_by,
        reason=decision.reason, decided_at=decision.decided_at, posting_id=decision.posting_id,
        recorded=decision.recorded,
    )


def _invocation_out(session: Session, invocation: ToolInvocation, decision: Decision | None) -> InvocationOut:
    return InvocationOut(
        id=invocation.id, session_id=invocation.session_id, created_at=invocation.created_at,
        tool_name=invocation.tool_name, tool_version=invocation.tool_version,
        model_provider=invocation.model_provider, model_id=invocation.model_id,
        prompt_version=invocation.prompt_version, temperature=invocation.temperature,
        input=invocation.input, result_amount_minor=invocation.result_amount_minor,
        result_currency=invocation.result_currency, citation=invocation.citation,
        proposed_entries=_labelled(session, invocation.proposed_entries), approval_required=invocation.approval_required,
        decision=None if decision is None else _decision_out(decision),
    )


def _evidence(session: Session, tenant_id: uuid.UUID, invocations: list[ToolInvocation]) -> dict[uuid.UUID, dict]:
    """Per proposal: its cited clauses, revealed for display like every other quote, in one query for the page."""
    cited = {i.id: [uuid.UUID(e) for e in (i.citation or {}).get("ids", [])] for i in invocations if i.approval_required}
    element_ids = [e for ids in cited.values() for e in ids]
    if not element_ids:
        return {}
    rows = retrieval_dao.evidence_rows(session, element_ids)
    quotes = iter(documents_dao.reveal(session, tenant_id, [element.text_redacted for element, _, _ in rows.values()],
                                       config.require("PII_VAULT_KEY")))
    revealed = {element_id: next(quotes) for element_id in rows}
    evidence = {}
    for invocation_id, ids in cited.items():
        found = [i for i in ids if i in rows]
        if not found:
            continue
        _, version, document = rows[found[0]]
        evidence[invocation_id] = {
            "document_title": document.title, "document_version": version.version,
            "sources": [SourceOut(element_id=str(i), page=rows[i][0].page_start, section=" › ".join(rows[i][0].section_path),
                                  quote=revealed[i]) for i in found],
        }
    return evidence


@router.get("", response_model=list[InvocationOut])
def list_tool_invocations(
    session: SessionDep,
    tenant_id: TenantDep,
    overlay_guest: Annotated[uuid.UUID | None, Depends(get_overlay_guest)],
    posting_id: uuid.UUID | None = None,
    pending: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    session_id: str | None = None,
) -> list[InvocationOut]:
    rows = list_invocations(session, tenant_id=tenant_id, posting_id=posting_id, pending=pending, limit=limit, session_id=session_id, overlay_guest=overlay_guest)
    turn_ids = {uuid.UUID(i.input["turn_id"]) for i, _ in rows if i.input.get("turn_id")}
    traces = assistant_dao.trace_ids(session, tenant_id, turn_ids)
    evidence = _evidence(session, tenant_id, [invocation for invocation, _ in rows])
    return [
        _invocation_out(session, invocation, decision).model_copy(update={
            "trace_id": traces.get(uuid.UUID(invocation.input["turn_id"])) if invocation.input.get("turn_id") else None,
            **evidence.get(invocation.id, {}),
        })
        for invocation, decision in rows
    ]


@router.post("/{invocation_id}/decision", status_code=201, response_model=DecisionOut)
def decide_tool_invocation(
    invocation_id: uuid.UUID, body: DecisionIn, session: SessionDep, tenant_id: TenantDep, guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)],
    overlay_guest: Annotated[uuid.UUID | None, Depends(require_overlay_guest)],
) -> DecisionOut:
    decision = decide(
        session, tenant_id=tenant_id, invocation_id=invocation_id,
        decision=body.decision, decided_by=decided_by(guest_id), reason=body.reason,
        overlay_guest=overlay_guest
    )
    invalidate_dashboard_stats(tenant_id)
    return _decision_out(decision)