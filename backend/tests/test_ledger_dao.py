import uuid
from datetime import datetime

import pytest

from app.ledger.dao import (
    EntryInput,
    PostingRequest,
    create_account,
    create_posting,
    get_posting,
    ledger_transaction,
    list_postings,
    reversal_ids_for,
    reverse_posting,
)
from app.ledger.errors import (
    IdempotencyKeyReused,
    PostingAlreadyReversed,
    PostingInvalid,
    PostingNotFound,
    RequestInProgress,
)
from app.ledger.models import Entry, Posting
from app.ledger.types import Direction, NormalBalance, PostingSource

DEBIT, CREDIT = Direction.debit, Direction.credit


@pytest.fixture()
def pair(db_session, tenant_id):
    cash = create_account(
        db_session, tenant_id=tenant_id, name="Cash", currency="CAD", normal_balance=NormalBalance.debit
    )
    revenue = create_account(
        db_session, tenant_id=tenant_id, name="Revenue", currency="CAD", normal_balance=NormalBalance.credit
    )
    return cash, revenue


def _request(tenant_id, pair, *, key=None, amount=1000, **overrides):
    cash, revenue = pair
    fields = dict(
        tenant_id=tenant_id,
        idempotency_key=key or str(uuid.uuid4()),
        description="Sale",
        entries=(EntryInput(cash.id, DEBIT, amount), EntryInput(revenue.id, CREDIT, amount)),
    )
    fields.update(overrides)
    return PostingRequest(**fields)


def _post(session, request):
    with ledger_transaction(session):
        return create_posting(session, request)


def test_create_account_persists_tenant_and_normal_balance(db_session, tenant_id):
    account = create_account(
        db_session, tenant_id=tenant_id, name="Cash", currency="CAD", normal_balance=NormalBalance.debit, gl_code="1000"
    )
    assert (account.tenant_id, account.currency, account.normal_balance, account.gl_code) == (
        tenant_id, "CAD", NormalBalance.debit, "1000",
    )


def test_new_posting_is_created_with_fingerprint_and_entries(db_session, tenant_id, pair):
    result = _post(db_session, _request(tenant_id, pair))
    assert result.replayed is False
    assert result.posting.source is PostingSource.api
    assert len(result.posting.request_fingerprint) == 64
    assert sorted(e.amount for e in result.posting.entries) == [1000, 1000]


def test_same_key_same_payload_replays_without_a_second_insert(db_session, tenant_id, pair):
    request = _request(tenant_id, pair)
    first = _post(db_session, request)
    second = _post(db_session, request)
    assert second.replayed is True
    assert second.posting.id == first.posting.id
    assert db_session.query(Entry).filter(Entry.posting_id == first.posting.id).count() == 2


def test_same_key_with_entries_reordered_is_still_a_replay(db_session, tenant_id, pair):
    request = _request(tenant_id, pair)
    _post(db_session, request)
    reordered = PostingRequest(
        tenant_id=request.tenant_id,
        idempotency_key=request.idempotency_key,
        description=request.description,
        entries=tuple(reversed(request.entries)),
    )
    assert _post(db_session, reordered).replayed is True


def test_same_key_different_payload_is_rejected(db_session, tenant_id, pair):
    key = str(uuid.uuid4())
    _post(db_session, _request(tenant_id, pair, key=key, amount=1000))
    with pytest.raises(IdempotencyKeyReused):
        _post(db_session, _request(tenant_id, pair, key=key, amount=999))


@pytest.mark.parametrize(
    ("entries_builder", "expected_reason"),
    [
        (lambda c, r: (EntryInput(c.id, DEBIT, 10),), "at least one debit and one credit"),
        (lambda c, r: (EntryInput(c.id, DEBIT, 10), EntryInput(r.id, CREDIT, 9)), "balance per currency"),
        (lambda c, r: (EntryInput(c.id, DEBIT, 0), EntryInput(r.id, CREDIT, 0)), "positive integer"),
        (lambda c, r: (EntryInput(c.id, DEBIT, True), EntryInput(r.id, CREDIT, True)), "positive integer"),
        (lambda c, r: (EntryInput(uuid.uuid4(), DEBIT, 5), EntryInput(r.id, CREDIT, 5)), "unknown accounts"),
    ],
)
def test_invalid_postings_are_rejected_before_the_database(db_session, tenant_id, pair, entries_builder, expected_reason):
    cash, revenue = pair
    request = _request(tenant_id, pair, entries=entries_builder(cash, revenue))
    with pytest.raises(PostingInvalid) as exc_info:
        _post(db_session, request)
    assert any(expected_reason in reason for reason in exc_info.value.reasons)


def test_naive_effective_at_is_rejected(db_session, tenant_id, pair):
    with pytest.raises(PostingInvalid) as exc_info:
        _post(db_session, _request(tenant_id, pair, effective_at=datetime(2026, 9, 30)))
    assert any("timezone" in reason for reason in exc_info.value.reasons)


def test_database_check_violation_is_translated_to_posting_invalid(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair, amount=1000)).posting
    cash, revenue = pair
    # Balanced, so Python validation passes, but it isn't a mirror: only the database catches this.
    not_a_mirror = _request(
        tenant_id,
        pair,
        entries=(EntryInput(cash.id, CREDIT, 400), EntryInput(revenue.id, DEBIT, 400)),
        reverses_posting_id=original.id,
    )
    with pytest.raises(PostingInvalid):
        _post(db_session, not_a_mirror)


def test_reverse_posting_mirrors_links_and_is_idempotent(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair, amount=750)).posting
    with ledger_transaction(db_session):
        first = reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id)
    with ledger_transaction(db_session):
        second = reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id)
    assert first.replayed is False and second.replayed is True
    assert first.posting.reverses_posting_id == original.id
    assert first.posting.effective_at == original.effective_at
    mirrored = {(e.account_id, e.direction, e.amount) for e in first.posting.entries}
    flipped = {(e.account_id, CREDIT if e.direction is DEBIT else DEBIT, e.amount) for e in original.entries}
    assert mirrored == flipped
    assert reversal_ids_for(db_session, [original.id]) == {original.id: first.posting.id}


def test_a_reversal_can_itself_be_reversed(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair)).posting
    with ledger_transaction(db_session):
        reversal = reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id).posting
    with ledger_transaction(db_session):
        re_reversal = reverse_posting(db_session, tenant_id=tenant_id, posting_id=reversal.id).posting
    assert re_reversal.reverses_posting_id == reversal.id


def test_second_reversal_under_a_different_key_is_rejected(db_session, tenant_id, pair):
    original = _post(db_session, _request(tenant_id, pair)).posting
    with ledger_transaction(db_session):
        reverse_posting(db_session, tenant_id=tenant_id, posting_id=original.id)
    cash, revenue = pair
    sneaky = _request(
        tenant_id,
        pair,
        entries=(EntryInput(cash.id, CREDIT, 1000), EntryInput(revenue.id, DEBIT, 1000)),
        reverses_posting_id=original.id,
    )
    with pytest.raises(PostingAlreadyReversed):
        _post(db_session, sneaky)


def test_reversing_an_unknown_posting_raises_not_found(db_session, tenant_id):
    with pytest.raises(PostingNotFound):
        with ledger_transaction(db_session):
            reverse_posting(db_session, tenant_id=tenant_id, posting_id=uuid.uuid4())


def test_get_posting_is_scoped_to_the_tenant(db_session, tenant_id, pair):
    posting = _post(db_session, _request(tenant_id, pair)).posting
    assert get_posting(db_session, tenant_id=tenant_id, posting_id=posting.id).id == posting.id
    with pytest.raises(PostingNotFound):
        get_posting(db_session, tenant_id=uuid.uuid4(), posting_id=posting.id)


def test_list_postings_hides_stress_traffic_and_paginates(db_session, tenant_id, pair):
    api_ids = [_post(db_session, _request(tenant_id, pair)).posting.id for _ in range(3)]
    _post(db_session, _request(tenant_id, pair, source=PostingSource.stress_test))

    page_one = list_postings(db_session, tenant_id=tenant_id, source=None, include_stress=False, limit=2, before=None)
    cursor = (page_one[-1].created_at, page_one[-1].id)
    page_two = list_postings(db_session, tenant_id=tenant_id, source=None, include_stress=False, limit=2, before=cursor)

    assert {p.id for p in page_one} | {p.id for p in page_two} == set(api_ids)
    assert not {p.id for p in page_one} & {p.id for p in page_two}
    only_stress = list_postings(
        db_session, tenant_id=tenant_id, source=PostingSource.stress_test, include_stress=False, limit=10, before=None
    )
    assert [p.source for p in only_stress] == [PostingSource.stress_test]


def test_concurrent_duplicate_times_out_as_request_in_progress(db_session, session_factory, tenant_id, pair):
    request = _request(tenant_id, pair)
    holder = session_factory()
    try:
        create_posting(holder, request)  # flushed, not committed: holds the unique-index slot
        with pytest.raises(RequestInProgress):
            _post(db_session, request)
    finally:
        holder.rollback()
        holder.close()
    assert db_session.query(Posting).filter(Posting.idempotency_key == request.idempotency_key).count() == 0
