import dataclasses
import uuid
from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.governance.errors import AlreadyDecided, InvocationNotFound, NotCritical
from app.governance.models import ToolInvocation, ToolInvocationDecision
from app.governance.types import ToolDecision
from app.ledger.dao import EntryInput, PostingRequest, create_posting, ledger_transaction
from app.ledger.fingerprint import canonical_json, sha256_hex
from app.ledger.types import Direction, PostingSource


@dataclasses.dataclass(frozen=True)
class ModelConfig:
    provider: str
    model_id: str  # exact snapshot, e.g. "gpt-4o-2024-08-06", never an alias
    prompt_version: str
    temperature: Decimal


@dataclasses.dataclass(frozen=True)
class InvocationRecord:
    tenant_id: uuid.UUID
    session_id: str
    tool_name: str
    tool_version: str
    model: ModelConfig
    input: Mapping[str, object]
    result_amount_minor: int | None = None
    result_currency: str | None = None
    citation: Mapping[str, object] | None = None
    proposed_entries: tuple[EntryInput, ...] | None = None  # present = critical, needs a human decision


def _entries_to_json(entries: tuple[EntryInput, ...]) -> list[dict]:
    return [{"account_id": str(e.account_id), "direction": e.direction.value, "amount": e.amount} for e in entries]


def _entries_from_json(data: list[dict]) -> tuple[EntryInput, ...]:
    return tuple(EntryInput(uuid.UUID(e["account_id"]), Direction(e["direction"]), int(e["amount"])) for e in data)


def record_invocation(session: Session, record: InvocationRecord) -> ToolInvocation:
    """Append an AI tool call with its full configuration. Called in-process by the chat pipeline."""
    proposed = None if record.proposed_entries is None else _entries_to_json(record.proposed_entries)
    invocation = ToolInvocation(
        tenant_id=record.tenant_id,
        session_id=record.session_id,
        tool_name=record.tool_name,
        tool_version=record.tool_version,
        model_provider=record.model.provider,
        model_id=record.model.model_id,
        prompt_version=record.model.prompt_version,
        temperature=record.model.temperature,
        input=dict(record.input),
        input_hash=sha256_hex(canonical_json(dict(record.input))),
        result_amount_minor=record.result_amount_minor,
        result_currency=record.result_currency,
        citation=None if record.citation is None else dict(record.citation),
        proposed_entries=proposed,
        approval_required=proposed is not None,
    )
    session.add(invocation)
    session.commit()
    return invocation


def list_invocations(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    posting_id: uuid.UUID | None = None,
    pending: bool | None = None,
    limit: int = 50,
) -> list[tuple[ToolInvocation, ToolInvocationDecision | None]]:
    query = (
        select(ToolInvocation, ToolInvocationDecision)
        .outerjoin(ToolInvocationDecision, ToolInvocationDecision.invocation_id == ToolInvocation.id)
        .where(ToolInvocation.tenant_id == tenant_id)
    )
    if posting_id is not None:
        query = query.where(ToolInvocationDecision.posting_id == posting_id)
    if pending is True:
        query = query.where(ToolInvocation.approval_required.is_(True), ToolInvocationDecision.invocation_id.is_(None))
    elif pending is False:
        query = query.where(ToolInvocationDecision.invocation_id.is_not(None))
    query = query.order_by(ToolInvocation.created_at.desc(), ToolInvocation.id.desc()).limit(limit)
    return [(invocation, decision) for invocation, decision in session.execute(query)]


def decide(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    invocation_id: uuid.UUID,
    decision: ToolDecision,
    decided_by: str,
    reason: str | None,
) -> ToolInvocationDecision:
    invocation = session.get(ToolInvocation, invocation_id)
    if invocation is None or invocation.tenant_id != tenant_id:
        raise InvocationNotFound(f"Tool invocation {invocation_id} does not exist.")
    if not invocation.approval_required:
        raise NotCritical(f"Tool invocation {invocation_id} proposed no ledger posting.")
    if session.get(ToolInvocationDecision, invocation_id) is not None:
        raise AlreadyDecided(f"Tool invocation {invocation_id} has already been decided.")

    with ledger_transaction(session):
        posting_id = None
        if decision is ToolDecision.approved:
            posted = create_posting(
                session,
                PostingRequest(
                    tenant_id=tenant_id,
                    idempotency_key=f"ai:{invocation_id}",
                    entries=_entries_from_json(invocation.proposed_entries),
                    description=f"Approved {invocation.tool_name} result ({invocation_id})",
                    source=PostingSource.ai_tool,
                ),
            )
            posting_id = posted.posting.id
        record = ToolInvocationDecision(
            invocation_id=invocation_id, decision=decision, decided_by=decided_by, reason=reason, posting_id=posting_id
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError as exc:  # a concurrent decision won the primary key
            raise AlreadyDecided(f"Tool invocation {invocation_id} has already been decided.") from exc
    return record