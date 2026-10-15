import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.ledger.types import Direction, NormalBalance
from tests.support import insert_raw_posting, make_account, make_tenant

DEBIT, CREDIT = Direction.debit, Direction.credit


def _sqlstate(exc_info) -> str:
    return exc_info.value.orig.sqlstate


def test_balanced_posting_is_accepted(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])


def test_unbalanced_posting_is_rejected(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 900)])
    assert _sqlstate(exc_info) == "23514"


def test_posting_without_entries_is_rejected(db_session, tenant_id):
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [])
    assert _sqlstate(exc_info) == "23514"


def test_posting_with_only_debits_is_rejected(db_session, tenant_id):
    cash = make_account(db_session, tenant_id)
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000)])
    assert _sqlstate(exc_info) == "23514"


def test_cross_currency_posting_that_only_nets_overall_is_rejected(db_session, tenant_id):
    cad = make_account(db_session, tenant_id, currency="CAD")
    usd = make_account(db_session, tenant_id, currency="USD")
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(cad.id, DEBIT, 1000), (usd.id, CREDIT, 1000)])
    assert _sqlstate(exc_info) == "23514"


def test_posting_balanced_per_currency_is_accepted(db_session, tenant_id):
    cad_a, cad_b = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    usd_a = make_account(db_session, tenant_id, currency="USD")
    usd_b = make_account(db_session, tenant_id, currency="USD")
    insert_raw_posting(
        db_session,
        tenant_id,
        [(cad_a.id, DEBIT, 1000), (cad_b.id, CREDIT, 1000), (usd_a.id, DEBIT, 750), (usd_b.id, CREDIT, 750)],
    )


def test_entry_on_another_tenants_account_is_rejected(db_session, tenant_id):
    other_tenant = make_tenant(db_session)
    mine = make_account(db_session, tenant_id)
    theirs = make_account(db_session, other_tenant)
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, [(mine.id, DEBIT, 500), (theirs.id, CREDIT, 500)])
    assert _sqlstate(exc_info) == "23514"


def test_reversal_must_mirror_the_original(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    original = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(
            db_session,
            tenant_id,
            [(cash.id, CREDIT, 900), (revenue.id, DEBIT, 900)],
            reverses_posting_id=original,
        )
    assert _sqlstate(exc_info) == "23514"


def test_exact_mirror_reversal_is_accepted(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    original = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])
    db_session.commit()
    insert_raw_posting(
        db_session,
        tenant_id,
        [(cash.id, CREDIT, 1000), (revenue.id, DEBIT, 1000)],
        reverses_posting_id=original,
    )


def test_posting_can_be_reversed_only_once(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    original = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 1000), (revenue.id, CREDIT, 1000)])
    db_session.commit()
    mirror = [(cash.id, CREDIT, 1000), (revenue.id, DEBIT, 1000)]
    insert_raw_posting(db_session, tenant_id, mirror, reverses_posting_id=original)
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        insert_raw_posting(db_session, tenant_id, mirror, reverses_posting_id=original)
    assert _sqlstate(exc_info) == "23505"


def test_app_role_cannot_update_or_delete_postings(db_session, tenant_id):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    posting_id = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 10), (revenue.id, CREDIT, 10)])
    db_session.commit()
    for statement in (
        "UPDATE postings SET description = 'x' WHERE id = :id",
        "DELETE FROM entries WHERE posting_id = :id",
    ):
        with pytest.raises(ProgrammingError) as exc_info:
            db_session.execute(text(statement), {"id": posting_id})
        assert _sqlstate(exc_info) == "42501"
        db_session.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE postings SET description = 'x' WHERE id = :id",
        "DELETE FROM entries WHERE posting_id = :id",
        "TRUNCATE entries",
    ],
)
def test_even_the_owner_cannot_rewrite_history(db_session, owner_session, tenant_id, statement):
    cash, revenue = make_account(db_session, tenant_id), make_account(db_session, tenant_id)
    posting_id = insert_raw_posting(db_session, tenant_id, [(cash.id, DEBIT, 10), (revenue.id, CREDIT, 10)])
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        owner_session.execute(text(statement), {"id": posting_id})
    assert _sqlstate(exc_info) == "23001"


def test_account_name_is_editable_by_app_role(db_session, tenant_id):
    account = make_account(db_session, tenant_id)
    db_session.execute(text("UPDATE accounts SET name = 'Renamed' WHERE id = :id"), {"id": account.id})
    db_session.commit()


def test_gl_code_can_be_set_once_but_never_changed(db_session, tenant_id):
    account = make_account(db_session, tenant_id)
    db_session.execute(text("UPDATE accounts SET gl_code = '4000' WHERE id = :id"), {"id": account.id})
    db_session.commit()
    with pytest.raises(IntegrityError) as exc_info:
        db_session.execute(text("UPDATE accounts SET gl_code = '4001' WHERE id = :id"), {"id": account.id})
    assert _sqlstate(exc_info) == "23001"


def test_account_currency_and_normal_balance_are_frozen_even_for_owner(db_session, owner_session, tenant_id):
    account = make_account(db_session, tenant_id, normal_balance=NormalBalance.debit)
    for statement in (
        "UPDATE accounts SET currency = 'USD' WHERE id = :id",
        "UPDATE accounts SET normal_balance = 'credit' WHERE id = :id",
        "DELETE FROM accounts WHERE id = :id",
    ):
        with pytest.raises(IntegrityError) as exc_info:
            owner_session.execute(text(statement), {"id": account.id})
        assert _sqlstate(exc_info) == "23001"
        owner_session.rollback()


def test_unknown_currency_is_rejected(db_session, tenant_id):
    with pytest.raises(IntegrityError) as exc_info:
        make_account(db_session, tenant_id, currency="XYZ")
    assert _sqlstate(exc_info) == "23503"
