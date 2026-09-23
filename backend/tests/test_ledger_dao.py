import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.ledger.dao import EntryInput, create_account, create_posting
from app.ledger.models import Direction, Entry, Posting


def test_create_account_persists_row(db_session):
    account = create_account(db_session, name="Cash", currency="USD")

    assert account.id is not None
    assert account.name == "Cash"
    assert account.currency == "USD"


def test_balanced_posting_succeeds(db_session):
    cash = create_account(db_session, name="Cash", currency="USD")
    revenue = create_account(db_session, name="Revenue", currency="USD")

    posting = create_posting(
        db_session,
        idempotency_key=str(uuid.uuid4()),
        description="Test sale",
        entries=[
            EntryInput(account_id=cash.id, direction=Direction.debit, amount=1000),
            EntryInput(account_id=revenue.id, direction=Direction.credit, amount=1000),
        ],
    )

    assert posting.id is not None
    stored_entries = (
        db_session.query(Entry).filter(Entry.posting_id == posting.id).all()
    )
    assert len(stored_entries) == 2


def test_unbalanced_posting_is_rejected(db_session):
    cash = create_account(db_session, name="Cash", currency="USD")
    revenue = create_account(db_session, name="Revenue", currency="USD")

    with pytest.raises(IntegrityError):
        create_posting(
            db_session,
            idempotency_key=str(uuid.uuid4()),
            description="Unbalanced",
            entries=[
                EntryInput(account_id=cash.id, direction=Direction.debit, amount=1000),
                EntryInput(account_id=revenue.id, direction=Direction.credit, amount=900),
            ],
        )


def test_unbalanced_posting_leaves_zero_partial_rows(db_session):
    cash = create_account(db_session, name="Cash", currency="USD")
    revenue = create_account(db_session, name="Revenue", currency="USD")
    key = str(uuid.uuid4())

    with pytest.raises(IntegrityError):
        create_posting(
            db_session,
            idempotency_key=key,
            description="Unbalanced",
            entries=[
                EntryInput(account_id=cash.id, direction=Direction.debit, amount=1000),
                EntryInput(account_id=revenue.id, direction=Direction.credit, amount=900),
            ],
        )

    db_session.rollback()
    assert db_session.query(Posting).filter(Posting.idempotency_key == key).count() == 0
    assert (
        db_session.query(Entry)
        .filter(Entry.account_id.in_([cash.id, revenue.id]))
        .count()
        == 0
    )
