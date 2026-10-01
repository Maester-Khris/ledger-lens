import dataclasses
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.governance.errors import AlreadyDecided, InvocationNotFound, NotCritical
from app.governance.models import GuestToolDecision, ToolInvocation, ToolInvocationDecision
from app.governance.types import ToolDecision
from app.ledger.dao import EntryInput, PostingRequest, check_posting, create_posting, ledger_transaction
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


# A real decision, or a demo guest's own (spec P2+P9). Both expose invocation_id, decision, decided_by, reason,
# decided_at, posting_id and recorded.
Decision = ToolInvocationDecision | GuestToolDecision


def _decisions_join(overlay_guest: uuid.UUID | None
                    ) -> tuple[type[ToolInvocationDecision] | type[GuestToolDecision], ColumnElement[bool]]:
    """The decision table a reader outer-joins: the real one, or this guest's overlay rows."""
    if overlay_guest is None:
        return ToolInvocationDecision, ToolInvocationDecision.invocation_id == ToolInvocation.id
    return GuestToolDecision, (GuestToolDecision.invocation_id == ToolInvocation.id) & (GuestToolDecision.guest_id == overlay_guest)


def _of_guest(guest_id: uuid.UUID) -> ColumnElement[bool]:
    """Proposals from this guest's own chats: in demo mode the tool runner records the guest in the input."""
    return ToolInvocation.input["guest_id"].astext == str(guest_id)


def _posting_request(invocation: ToolInvocation) -> PostingRequest:
    return PostingRequest(
        tenant_id=invocation.tenant_id,
        idempotency_key=f"ai:{invocation.id}",
        entries=_entries_from_json(invocation.proposed_entries),
        description=f"Approved {invocation.tool_name} result ({invocation.id})",
        source=PostingSource.ai_tool,
    )


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
    session_id: str | None = None,
    overlay_guest: uuid.UUID | None = None,
) -> list[tuple[ToolInvocation, Decision | None]]:
    if posting_id is not None:
        overlay_guest = None  # the provenance of a real posting always reads the real decision
    decisions, joined = _decisions_join(overlay_guest)
    query = select(ToolInvocation, decisions).outerjoin(decisions, joined).where(ToolInvocation.tenant_id == tenant_id)
    if overlay_guest is not None:
        query = query.where(_of_guest(overlay_guest))
    if posting_id is not None:
        query = query.where(ToolInvocationDecision.posting_id == posting_id)
    if pending is True:
        query = query.where(ToolInvocation.approval_required.is_(True), decisions.invocation_id.is_(None))
    elif pending is False:
        query = query.where(decisions.invocation_id.is_not(None))
    if session_id is not None:
        query = query.where(ToolInvocation.session_id == session_id)
    query = query.order_by(ToolInvocation.created_at.desc(), ToolInvocation.id.desc()).limit(limit)
    return [(invocation, decision) for invocation, decision in session.execute(query)]


def invocations_for_document(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID,
                             overlay_guest: uuid.UUID | None = None) -> list[tuple[ToolInvocation, Decision | None]]:
    # ponytail: scans tool_invocations by JSONB; add an index on (tenant_id, (input->>'document_id')) when volume grows
    decisions, joined = _decisions_join(overlay_guest)
    query = (
        select(ToolInvocation, decisions)
        .outerjoin(decisions, joined)
        .where(ToolInvocation.tenant_id == tenant_id, ToolInvocation.input["document_id"].astext == str(document_id))
        .order_by(ToolInvocation.created_at)
    )
    if overlay_guest is not None:
        query = query.where(_of_guest(overlay_guest))
    return [(i, d) for i, d in session.execute(query)]


def decide(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    invocation_id: uuid.UUID,
    decision: ToolDecision,
    decided_by: str,
    reason: str | None,
    overlay_guest: uuid.UUID | None = None,
) -> Decision:
    invocation = session.get(ToolInvocation, invocation_id)
    if invocation is None or invocation.tenant_id != tenant_id or (
        overlay_guest is not None and invocation.input.get("guest_id") != str(overlay_guest)
    ):  # another guest's proposal is reported as missing, never as existing
        raise InvocationNotFound(f"Tool invocation {invocation_id} does not exist.")
    if not invocation.approval_required:
        raise NotCritical(f"Tool invocation {invocation_id} proposed no ledger posting.")
    if overlay_guest is not None:
        return _decide_as_guest(session, invocation, decision=decision, reason=reason, guest_id=overlay_guest)
    if session.get(ToolInvocationDecision, invocation_id) is not None:
        raise AlreadyDecided(f"Tool invocation {invocation_id} has already been decided.")

    with ledger_transaction(session):
        posting_id = None
        if decision is ToolDecision.approved:
            posted = create_posting(session, _posting_request(invocation))
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


def _decide_as_guest(session: Session, invocation: ToolInvocation, *, decision: ToolDecision, reason: str | None,
                     guest_id: uuid.UUID) -> GuestToolDecision:
    """Demo mode: the ledger's own validation runs, nothing is posted, and the decision goes to the guest's overlay."""
    if session.get(GuestToolDecision, (guest_id, invocation.id)) is not None:
        raise AlreadyDecided(f"Tool invocation {invocation.id} has already been decided.")
    if decision is ToolDecision.approved:
        check_posting(session, _posting_request(invocation))
    record = GuestToolDecision(guest_id=guest_id, invocation_id=invocation.id, decision=decision, reason=reason)
    session.add(record)
    try:
        session.commit()
    except IntegrityError as exc:  # a concurrent decision by the same guest won the primary key
        session.rollback()
        raise AlreadyDecided(f"Tool invocation {invocation.id} has already been decided.") from exc
    return record


def count_pending(session: Session, tenant_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> int:
    decisions, joined = _decisions_join(overlay_guest)
    query = (
        select(func.count())
        .select_from(ToolInvocation)
        .outerjoin(decisions, joined)
        .where(
            ToolInvocation.tenant_id == tenant_id,
            ToolInvocation.approval_required.is_(True),
            decisions.invocation_id.is_(None),
        )
    )
    if overlay_guest is not None:
        query = query.where(_of_guest(overlay_guest))
    return session.scalar(query) or 0


def purge_guest_decisions(session: Session, guest_ids: Sequence[uuid.UUID]) -> None:
    """Delete these guests' overlay decisions (the 24-hour purge). The caller commits."""
    session.execute(delete(GuestToolDecision).where(GuestToolDecision.guest_id.in_(guest_ids)))
