import base64
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt
from sqlalchemy.orm import Session

from app.deps import get_session, get_tenant_id
from app.ledger.dao import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    EntryInput,
    PostingRequest,
    PostingResult,
    create_posting,
    get_posting,
    ledger_transaction,
    list_postings,
    reversal_ids_for,
    reverse_posting,
)
from app.ledger.errors import CursorInvalid, IdempotencyKeyInvalid, IdempotencyKeyMissing
from app.ledger.models import Posting
from app.ledger.types import Direction, PostingSource

router = APIRouter(prefix="/postings", tags=["postings"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class EntryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: uuid.UUID
    direction: Direction
    amount: StrictInt = Field(gt=0, description="Amount in minor currency units (cents).")


class PostingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=500)
    effective_at: AwareDatetime | None = None
    source: Literal["api", "stress_test"] = "api"
    entries: list[EntryIn]


class ReversalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = Field(default=None, max_length=500)


class EntryOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    direction: Direction
    amount: int


class PostingOut(BaseModel):
    id: uuid.UUID
    idempotency_key: str
    description: str | None
    effective_at: datetime
    created_at: datetime
    source: PostingSource
    reverses_posting_id: uuid.UUID | None
    reversed_by_posting_id: uuid.UUID | None
    entries: list[EntryOut]


class PostingPage(BaseModel):
    items: list[PostingOut]
    next_cursor: str | None


def posting_out(posting: Posting, reversed_by: uuid.UUID | None) -> PostingOut:
    return PostingOut(
        id=posting.id,
        idempotency_key=posting.idempotency_key,
        description=posting.description,
        effective_at=posting.effective_at,
        created_at=posting.created_at,
        source=posting.source,
        reverses_posting_id=posting.reverses_posting_id,
        reversed_by_posting_id=reversed_by,
        entries=[EntryOut(id=e.id, account_id=e.account_id, direction=e.direction, amount=e.amount) for e in posting.entries],
    )


def mark_replay(response: Response, replayed: bool) -> None:
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"


def _require_idempotency_key(raw: str | None) -> str:
    key = (raw or "").strip()
    if not key:
        raise IdempotencyKeyMissing("This operation requires an Idempotency-Key header.")
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise IdempotencyKeyInvalid(f"Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters.")
    return key


def _encode_cursor(posting: Posting) -> str:
    raw = f"{posting.created_at.isoformat()}|{posting.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, posting_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(created_at), uuid.UUID(posting_id)
    except ValueError as exc:  # also covers binascii.Error and UnicodeDecodeError
        raise CursorInvalid("The cursor is not a value previously returned by this API.") from exc


def _respond(session: Session, response: Response, result: PostingResult) -> PostingOut:
    mark_replay(response, result.replayed)
    reversed_by = reversal_ids_for(session, [result.posting.id]).get(result.posting.id)
    return posting_out(result.posting, reversed_by)


@router.post("", status_code=201, response_model=PostingOut)
def create_posting_endpoint(
    body: PostingIn,
    response: Response,
    session: SessionDep,
    tenant_id: TenantDep,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> PostingOut:
    key = _require_idempotency_key(idempotency_key)
    request = PostingRequest(
        tenant_id=tenant_id,
        idempotency_key=key,
        description=body.description,
        effective_at=body.effective_at,
        source=PostingSource(body.source),
        entries=tuple(EntryInput(e.account_id, e.direction, e.amount) for e in body.entries),
    )
    with ledger_transaction(session):
        result = create_posting(session, request)
    return _respond(session, response, result)


@router.post("/{posting_id}/reversal", status_code=201, response_model=PostingOut)
def reverse_posting_endpoint(
    posting_id: uuid.UUID,
    response: Response,
    session: SessionDep,
    tenant_id: TenantDep,
    body: ReversalIn | None = None,
) -> PostingOut:
    with ledger_transaction(session):
        result = reverse_posting(
            session, tenant_id=tenant_id, posting_id=posting_id, description=body.description if body else None
        )
    return _respond(session, response, result)


@router.get("", response_model=PostingPage)
def list_postings_endpoint(
    session: SessionDep,
    tenant_id: TenantDep,
    source: PostingSource | None = None,
    include_stress: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
) -> PostingPage:
    before = _decode_cursor(cursor) if cursor else None
    postings = list_postings(
        session, tenant_id=tenant_id, source=source, include_stress=include_stress, limit=limit, before=before
    )
    reversals = reversal_ids_for(session, [p.id for p in postings])
    next_cursor = _encode_cursor(postings[-1]) if len(postings) == limit else None
    return PostingPage(items=[posting_out(p, reversals.get(p.id)) for p in postings], next_cursor=next_cursor)


@router.get("/{posting_id}", response_model=PostingOut)
def get_posting_endpoint(posting_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> PostingOut:
    posting = get_posting(session, tenant_id=tenant_id, posting_id=posting_id)
    return posting_out(posting, reversal_ids_for(session, [posting.id]).get(posting.id))
