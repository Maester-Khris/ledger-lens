import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.deps import DECIDED_BY, get_session, get_tenant_id
from app.governance.dao import decide, list_invocations
from app.governance.models import ToolInvocation, ToolInvocationDecision
from app.governance.types import ToolDecision

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


class InvocationOut(BaseModel):
    id: uuid.UUID
    session_id: str
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


def _decision_out(decision: ToolInvocationDecision) -> DecisionOut:
    return DecisionOut(
        invocation_id=decision.invocation_id, decision=decision.decision, decided_by=decision.decided_by,
        reason=decision.reason, decided_at=decision.decided_at, posting_id=decision.posting_id,
    )


def _invocation_out(invocation: ToolInvocation, decision: ToolInvocationDecision | None) -> InvocationOut:
    return InvocationOut(
        id=invocation.id, session_id=invocation.session_id, created_at=invocation.created_at,
        tool_name=invocation.tool_name, tool_version=invocation.tool_version,
        model_provider=invocation.model_provider, model_id=invocation.model_id,
        prompt_version=invocation.prompt_version, temperature=invocation.temperature,
        input=invocation.input, result_amount_minor=invocation.result_amount_minor,
        result_currency=invocation.result_currency, citation=invocation.citation,
        proposed_entries=invocation.proposed_entries, approval_required=invocation.approval_required,
        decision=None if decision is None else _decision_out(decision),
    )


@router.get("", response_model=list[InvocationOut])
def list_tool_invocations(
    session: SessionDep,
    tenant_id: TenantDep,
    posting_id: uuid.UUID | None = None,
    pending: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[InvocationOut]:
    rows = list_invocations(session, tenant_id=tenant_id, posting_id=posting_id, pending=pending, limit=limit)
    return [_invocation_out(invocation, decision) for invocation, decision in rows]


@router.post("/{invocation_id}/decision", status_code=201, response_model=DecisionOut)
def decide_tool_invocation(
    invocation_id: uuid.UUID, body: DecisionIn, session: SessionDep, tenant_id: TenantDep
) -> DecisionOut:
    decision = decide(
        session, tenant_id=tenant_id, invocation_id=invocation_id,
        decision=body.decision, decided_by=DECIDED_BY, reason=body.reason,
    )
    return _decision_out(decision)