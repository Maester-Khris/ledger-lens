import dataclasses
import uuid
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, date, time, timedelta, timezone

from sqlalchemy import select, text, tuple_, distinct, func, case
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, selectinload

from app.ledger.errors import (
    AppendOnlyViolation,
    IdempotencyKeyReused,
    PostingAlreadyReversed,
    PostingInvalid,
    PostingNotFound,
    RequestInProgress,
)
from app.ledger.fingerprint import posting_fingerprint
from app.ledger.models import Account, Entry, Posting
from app.ledger.types import Direction, NormalBalance, PostingSource

LOCK_TIMEOUT = "2s"
# Bounds how long any ledger statement can run. The GL export's settle margin depends on this.
STATEMENT_TIMEOUT = "10s"
MAX_IDEMPOTENCY_KEY_LENGTH = 255

UNIQUE_IDEMPOTENCY_CONSTRAINT = "uq_postings_tenant_idempotency_key"
UNIQUE_REVERSAL_CONSTRAINT = "uq_postings_reverses_posting_id"
SQLSTATE_CHECK_VIOLATION = "23514"
SQLSTATE_RESTRICT_VIOLATION = "23001"
SQLSTATE_LOCK_NOT_AVAILABLE = "55P03"


@dataclasses.dataclass(frozen=True)
class EntryInput:
    account_id: uuid.UUID
    direction: Direction
    amount: int


@dataclasses.dataclass(frozen=True)
class PostingRequest:
    tenant_id: uuid.UUID
    idempotency_key: str
    entries: tuple[EntryInput, ...]
    description: str | None = None
    source: PostingSource = PostingSource.api
    effective_at: datetime | None = None
    reverses_posting_id: uuid.UUID | None = None


@dataclasses.dataclass(frozen=True)
class PostingResult:
    posting: Posting
    replayed: bool


def create_account(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    name: str,
    currency: str,
    normal_balance: NormalBalance,
    gl_code: str | None = None,
) -> Account:
    account = Account(
        tenant_id=tenant_id, name=name, currency=currency, normal_balance=normal_balance, gl_code=gl_code
    )
    session.add(account)
    session.commit()
    return account


def _sqlstate(exc: Exception) -> str | None:
    return getattr(getattr(exc, "orig", None), "sqlstate", None)


def _constraint_name(exc: Exception) -> str | None:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "constraint_name", None)


def _primary_message(exc: Exception) -> str:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return getattr(diag, "message_primary", None) or str(exc)


@contextmanager
def ledger_transaction(session: Session) -> Iterator[None]:
    """Unit of work for ledger writes: bounded lock wait and statement time, commit
    on success, database invariant violations translated into domain errors."""
    try:
        session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
        session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
        yield
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        state = _sqlstate(exc)
        if state == SQLSTATE_CHECK_VIOLATION:
            raise PostingInvalid([_primary_message(exc)]) from exc
        if state == SQLSTATE_RESTRICT_VIOLATION:
            raise AppendOnlyViolation(_primary_message(exc)) from exc
        raise
    except OperationalError as exc:
        session.rollback()
        if _sqlstate(exc) == SQLSTATE_LOCK_NOT_AVAILABLE:
            raise RequestInProgress(
                "A request with this Idempotency-Key is still being processed; retry shortly."
            ) from exc
        raise
    except BaseException:
        session.rollback()
        raise


def _accounts_by_id(session: Session, request: PostingRequest) -> dict[uuid.UUID, Account]:
    ids = {entry.account_id for entry in request.entries}
    if not ids:
        return {}
    return {account.id: account for account in session.scalars(select(Account).where(Account.id.in_(ids)))}


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate(request: PostingRequest, accounts: Mapping[uuid.UUID, Account]) -> None:
    reasons: list[str] = []
    if not 1 <= len(request.idempotency_key) <= MAX_IDEMPOTENCY_KEY_LENGTH:
        reasons.append(f"idempotency_key must be 1-{MAX_IDEMPOTENCY_KEY_LENGTH} characters")
    if request.effective_at is not None and request.effective_at.tzinfo is None:
        reasons.append("effective_at must include a timezone offset")

    directions = {entry.direction for entry in request.entries}
    if Direction.debit not in directions or Direction.credit not in directions:
        reasons.append("a posting needs at least one debit and one credit entry")

    bad_amounts = [entry.amount for entry in request.entries if not _is_positive_int(entry.amount)]
    for amount in bad_amounts:
        reasons.append(f"entry amount must be a positive integer in minor units, got {amount!r}")

    missing = sorted({str(entry.account_id) for entry in request.entries if entry.account_id not in accounts})
    if missing:
        reasons.append(f"unknown accounts: {', '.join(missing)}")

    foreign = sorted({str(a.id) for a in accounts.values() if a.tenant_id != request.tenant_id})
    if foreign:
        reasons.append(f"accounts belong to another tenant: {', '.join(foreign)}")

    if not missing and not bad_amounts:
        net_by_currency: dict[str, int] = defaultdict(int)
        for entry in request.entries:
            signed = entry.amount if entry.direction is Direction.debit else -entry.amount
            net_by_currency[accounts[entry.account_id].currency] += signed
        unbalanced = sorted((c, v) for c, v in net_by_currency.items() if v != 0)
        if unbalanced:
            reasons.append(
                "debits and credits must balance per currency: "
                + ", ".join(f"{currency} off by {value}" for currency, value in unbalanced)
            )

    if reasons:
        raise PostingInvalid(reasons)


def _fingerprint(request: PostingRequest) -> str:
    return posting_fingerprint(
        description=request.description,
        effective_at=request.effective_at,
        source=request.source.value,
        reverses_posting_id=request.reverses_posting_id,
        entries=[(e.account_id, e.direction.value, e.amount) for e in request.entries],
    )


def _replay_or_reject(session: Session, request: PostingRequest, fingerprint: str) -> PostingResult:
    existing = session.scalars(
        select(Posting)
        .options(selectinload(Posting.entries))
        .where(Posting.tenant_id == request.tenant_id, Posting.idempotency_key == request.idempotency_key)
    ).one()
    if existing.request_fingerprint == fingerprint:
        return PostingResult(posting=existing, replayed=True)
    raise IdempotencyKeyReused(
        f"Idempotency-Key {request.idempotency_key!r} was already used with a different payload."
    )


def create_posting(session: Session, request: PostingRequest) -> PostingResult:
    """Add a validated posting to the session's current transaction; call inside ledger_transaction.

    If the same idempotency key was already used with the same payload, the
    existing posting is returned with replayed=True and nothing new is written.
    """
    accounts = _accounts_by_id(session, request)
    _validate(request, accounts)
    fingerprint = _fingerprint(request)

    posting = Posting(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        description=request.description,
        request_fingerprint=fingerprint,
        source=request.source,
        reverses_posting_id=request.reverses_posting_id,
    )
    if request.effective_at is not None:
        posting.effective_at = request.effective_at

    try:
        # Savepoint: a duplicate key rolls back only this insert, so the caller's
        # transaction can still read the winner and replay it.
        with session.begin_nested():
            session.add(posting)
            session.flush()
    except IntegrityError as exc:
        constraint = _constraint_name(exc)
        if constraint == UNIQUE_IDEMPOTENCY_CONSTRAINT:
            return _replay_or_reject(session, request, fingerprint)
        if constraint == UNIQUE_REVERSAL_CONSTRAINT:
            # Could be a replay (same idempotency key already has this reversal) or a
            # genuine second reversal under a different key. Check the idempotency key first.
            existing = session.scalars(
                select(Posting)
                .options(selectinload(Posting.entries))
                .where(Posting.tenant_id == request.tenant_id, Posting.idempotency_key == request.idempotency_key)
            ).one_or_none()
            if existing is not None:
                if existing.request_fingerprint == fingerprint:
                    return PostingResult(posting=existing, replayed=True)
                raise IdempotencyKeyReused(
                    f"Idempotency-Key {request.idempotency_key!r} was already used with a different payload."
                )
            raise PostingAlreadyReversed(
                f"Posting {request.reverses_posting_id} has already been reversed."
            ) from exc
        raise

    posting.entries.extend(
        Entry(account_id=e.account_id, direction=e.direction, amount=e.amount) for e in request.entries
    )
    session.flush()
    return PostingResult(posting=posting, replayed=False)


def get_posting(session: Session, *, tenant_id: uuid.UUID, posting_id: uuid.UUID) -> Posting:
    posting = session.scalars(
        select(Posting)
        .options(selectinload(Posting.entries))
        .where(Posting.id == posting_id, Posting.tenant_id == tenant_id)
    ).one_or_none()
    if posting is None:
        raise PostingNotFound(f"Posting {posting_id} does not exist.")
    return posting


def _opposite(direction: Direction) -> Direction:
    return Direction.credit if direction is Direction.debit else Direction.debit


def reverse_posting(
    session: Session, *, tenant_id: uuid.UUID, posting_id: uuid.UUID, description: str | None = None
) -> PostingResult:
    original = get_posting(session, tenant_id=tenant_id, posting_id=posting_id)
    mirrored = tuple(
        EntryInput(account_id=e.account_id, direction=_opposite(e.direction), amount=e.amount)
        for e in original.entries
    )
    return create_posting(
        session,
        PostingRequest(
            tenant_id=tenant_id,
            idempotency_key=f"reverse:{posting_id}",
            entries=mirrored,
            description=description or f"Reversal of {posting_id}",
            source=PostingSource.api,
            effective_at=original.effective_at,
            reverses_posting_id=posting_id,
        ),
    )


def list_postings(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    source: PostingSource | None,
    include_stress: bool,
    limit: int,
    before: tuple[datetime, uuid.UUID] | None,
) -> list[Posting]:
    query = select(Posting).options(selectinload(Posting.entries)).where(Posting.tenant_id == tenant_id)
    if source is not None:
        query = query.where(Posting.source == source)
    elif not include_stress:
        query = query.where(Posting.source != PostingSource.stress_test)
    if before is not None:
        query = query.where(tuple_(Posting.created_at, Posting.id) < tuple_(before[0], before[1]))
    query = query.order_by(Posting.created_at.desc(), Posting.id.desc()).limit(limit)
    return list(session.scalars(query))


def reversal_ids_for(session: Session, posting_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not posting_ids:
        return {}
    rows = session.execute(
        select(Posting.reverses_posting_id, Posting.id).where(Posting.reverses_posting_id.in_(posting_ids))
    )
    return {original_id: reversal_id for original_id, reversal_id in rows}

@dataclasses.dataclass(frozen=True)
class GlCodeTotal:
    gl_code: str
    account_names: tuple[str, ...]
    debit_minor: int
    credit_minor: int
    posting_count: int


@dataclasses.dataclass(frozen=True)
class GlTotals:
    lines: tuple[GlCodeTotal, ...]
    accounts_missing_gl_code: tuple[uuid.UUID, ...]


def sum_entries_by_gl_code(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    currency: str,
    period_start: date,
    period_end: date,
    cutoff: datetime,
) -> GlTotals:
    """Per-GL-code totals for postings effective in [period_start, period_end] (UTC days)
    and recorded at or before cutoff. Stress-test traffic is always excluded."""
    window_start = datetime.combine(period_start, time.min, tzinfo=timezone.utc)
    window_end = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    in_scope = (
        Posting.tenant_id == tenant_id,
        Account.currency == currency,
        Posting.effective_at >= window_start,
        Posting.effective_at < window_end,
        Posting.created_at <= cutoff,
        Posting.source != PostingSource.stress_test,
    )

    def joined(*columns):
        return (
            select(*columns)
            .select_from(Entry)
            .join(Posting, Posting.id == Entry.posting_id)
            .join(Account, Account.id == Entry.account_id)
        )

    missing = session.scalars(joined(distinct(Account.id)).where(*in_scope, Account.gl_code.is_(None))).all()

    debit = func.coalesce(func.sum(case((Entry.direction == Direction.debit, Entry.amount), else_=0)), 0)
    credit = func.coalesce(func.sum(case((Entry.direction == Direction.credit, Entry.amount), else_=0)), 0)
    rows = session.execute(
        joined(Account.gl_code, func.array_agg(distinct(Account.name)), debit, credit, func.count(distinct(Posting.id)))
        .where(*in_scope, Account.gl_code.is_not(None))
        .group_by(Account.gl_code)
        .order_by(Account.gl_code)
    ).all()
    lines = tuple(
        GlCodeTotal(gl_code, tuple(sorted(names)), int(debit_sum), int(credit_sum), int(count))
        for gl_code, names, debit_sum, credit_sum, count in rows
    )
    return GlTotals(lines=lines, accounts_missing_gl_code=tuple(sorted(missing, key=str)))