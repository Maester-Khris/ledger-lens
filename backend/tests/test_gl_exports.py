import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.billing.dao import run_household_fee
from app.ledger.dao import EntryInput, PostingRequest, create_posting, ledger_transaction
from app.ledger.types import Direction, PostingSource
from app.reporting.dao import create_gl_export, export_csv
from app.reporting.errors import GlCodeMissing
from tests.support import build_fee_scenario, make_account

Q3 = {"period_start": date(2026, 7, 1), "period_end": date(2026, 9, 30)}
NO_SETTLE = timedelta(0)


def _billed_scenario(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    run_household_fee(db_session, tenant_id=tenant_id, household_id=scenario.household_id, **Q3)
    return scenario


def _export(db_session, tenant_id, **period):
    return create_gl_export(db_session, tenant_id=tenant_id, currency="CAD", settle_margin=NO_SETTLE, **(period or Q3))


def test_export_groups_the_fee_posting_by_gl_code(db_session, tenant_id):
    _billed_scenario(db_session, tenant_id)
    export = _export(db_session, tenant_id)
    _, content = export_csv(db_session, tenant_id=tenant_id, export_id=export.id)
    lines = content.splitlines()
    assert lines[1].startswith("2100,") and ",CAD,3669.41,0.00,3669.41,1" in lines[1]
    assert lines[2] == "4000,Advisory Fee Revenue,CAD,0.00,3669.41,-3669.41,1"
    assert lines[3] == "TOTAL,,CAD,3669.41,3669.41,0.00,"
    assert (export.line_count, export.total_debits_minor, export.total_credits_minor) == (2, 366_941, 366_941)


def test_regeneration_matches_the_hash_after_later_postings(db_session, tenant_id):
    scenario = _billed_scenario(db_session, tenant_id)
    export = _export(db_session, tenant_id)
    first, _ = scenario.client_account_ids
    with ledger_transaction(db_session):  # later posting, same period: after the cutoff, so excluded
        create_posting(db_session, PostingRequest(
            tenant_id=tenant_id, idempotency_key=str(uuid.uuid4()),
            entries=(EntryInput(first, Direction.debit, 5), EntryInput(scenario.revenue_account_id, Direction.credit, 5)),
        ))
    regenerated_export, content = export_csv(db_session, tenant_id=tenant_id, export_id=export.id)
    assert regenerated_export.content_sha256 == export.content_sha256
    assert "TOTAL,,CAD,3669.41,3669.41,0.00," in content


def test_stress_postings_are_excluded(db_session, tenant_id):
    scenario = _billed_scenario(db_session, tenant_id)
    first, _ = scenario.client_account_ids
    with ledger_transaction(db_session):
        create_posting(db_session, PostingRequest(
            tenant_id=tenant_id, idempotency_key=str(uuid.uuid4()), source=PostingSource.stress_test,
            entries=(EntryInput(first, Direction.debit, 7), EntryInput(scenario.revenue_account_id, Direction.credit, 7)),
        ))
    export = _export(db_session, tenant_id)
    assert export.total_debits_minor == 366_941


def test_accounts_without_gl_code_block_the_export(db_session, tenant_id):
    scenario = _billed_scenario(db_session, tenant_id)
    uncoded = make_account(db_session, tenant_id)
    with ledger_transaction(db_session):
        create_posting(db_session, PostingRequest(
            tenant_id=tenant_id, idempotency_key=str(uuid.uuid4()),
            effective_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            entries=(EntryInput(uncoded.id, Direction.debit, 3), EntryInput(scenario.revenue_account_id, Direction.credit, 3)),
        ))
    with pytest.raises(GlCodeMissing) as exc_info:
        _export(db_session, tenant_id)
    assert exc_info.value.extensions["account_ids"] == [str(uncoded.id)]


def test_empty_period_exports_header_and_zero_total(db_session, tenant_id):
    export = _export(db_session, tenant_id, period_start=date(2020, 1, 1), period_end=date(2020, 3, 31))
    _, content = export_csv(db_session, tenant_id=tenant_id, export_id=export.id)
    assert content.splitlines()[-1] == "TOTAL,,CAD,0.00,0.00,0.00,"
    assert export.line_count == 0


# --- API -------------------------------------------------------------------------------------

@pytest.fixture()
def no_settle(client):
    from app.main import app
    from app.routes.gl_exports import get_settle_margin

    app.dependency_overrides[get_settle_margin] = lambda: NO_SETTLE
    return client


def test_export_endpoints_create_and_download(no_settle, db_session, tenant_id):
    _billed_scenario(db_session, tenant_id)
    created = no_settle.post("/gl-exports", json={"period_start": "2026-07-01", "period_end": "2026-09-30", "currency": "CAD"})
    assert created.status_code == 201
    download = no_settle.get(created.json()["csv_url"])
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert download.text.splitlines()[-1] == "TOTAL,,CAD,3669.41,3669.41,0.00,"


def test_export_endpoint_errors(no_settle):
    assert no_settle.get(f"/gl-exports/{uuid.uuid4()}.csv").status_code == 404
    unknown = no_settle.post("/gl-exports", json={"period_start": "2026-07-01", "period_end": "2026-09-30", "currency": "EUR"})
    assert unknown.status_code == 422 and unknown.json()["type"] == "/problems/unknown-currency"