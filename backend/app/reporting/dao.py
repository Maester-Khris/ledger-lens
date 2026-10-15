import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ledger.dao import sum_entries_by_gl_code
from app.ledger.models import Currency
from app.ranges import date_range, range_end_inclusive
from app.reporting.errors import GlCodeMissing, GlExportIntegrityError, GlExportNotFound, UnknownCurrency
from app.reporting.gl_csv import RenderedExport, render
from app.reporting.models import GlExport

# ponytail: postings carry created_at = their transaction's start time, so a transaction that
# began before the cutoff but commits after the export read would appear on regeneration.
# Ledger statements are capped at 10s (ledger.dao.STATEMENT_TIMEOUT) and a posting is a handful
# of statements, so a 60s margin excludes them. Upgrade path if long transactions ever appear:
# cut off by a commit-ordered marker (pg_current_snapshot) instead of a timestamp.
SETTLE_MARGIN = timedelta(seconds=60)


def _render(
    session: Session, tenant_id: uuid.UUID, currency: str, period_start: date, period_end: date, cutoff: datetime
) -> RenderedExport:
    currency_row = session.get(Currency, currency)
    if currency_row is None:
        raise UnknownCurrency(f"Currency {currency!r} is not configured.")
    totals = sum_entries_by_gl_code(
        session, tenant_id=tenant_id, currency=currency, period_start=period_start, period_end=period_end, cutoff=cutoff
    )
    if totals.accounts_missing_gl_code:
        missing = [str(account_id) for account_id in totals.accounts_missing_gl_code]
        raise GlCodeMissing(
            f"{len(missing)} account(s) with activity in this period have no GL code; set one before exporting.",
            account_ids=missing,
        )
    return render(totals.lines, currency=currency, minor_units=currency_row.minor_units)


def create_gl_export(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    currency: str,
    period_start: date,
    period_end: date,
    settle_margin: timedelta = SETTLE_MARGIN,
) -> GlExport:
    cutoff = session.execute(select(func.now())).scalar_one() - settle_margin
    rendered = _render(session, tenant_id, currency, period_start, period_end, cutoff)
    export = GlExport(
        tenant_id=tenant_id,
        period=date_range(period_start, period_end),
        currency=currency,
        cutoff=cutoff,
        line_count=rendered.line_count,
        total_debits_minor=rendered.total_debits_minor,
        total_credits_minor=rendered.total_credits_minor,
        content_sha256=rendered.sha256,
    )
    session.add(export)
    session.commit()
    return export


def export_csv(session: Session, *, tenant_id: uuid.UUID, export_id: uuid.UUID) -> tuple[GlExport, str]:
    export = session.get(GlExport, export_id)
    if export is None or export.tenant_id != tenant_id:
        raise GlExportNotFound(f"GL export {export_id} does not exist.")
    rendered = _render(
        session, tenant_id, export.currency, export.period.lower, range_end_inclusive(export.period), export.cutoff
    )
    if rendered.sha256 != export.content_sha256:
        raise GlExportIntegrityError(f"GL export {export_id} no longer reproduces; the ledger history changed.")
    return export, rendered.content