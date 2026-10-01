import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import delete, func, select

from app.contracts.errors import FieldAlreadyReviewed, FieldNotFound, ReviewInvalid
from app.contracts.fields import FieldResult
from app.contracts.models import ExtractedField, ExtractionRun, FieldReview, GuestFieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from app.documents import dao as documents_dao
from app.documents.models import DocumentVersion
from datetime import date, datetime
from app.billing import dao as billing_dao
from app.billing.errors import NoScheduleAssigned
from app.contracts.terms import (COMING_SOON, SERVED_STATUSES, FieldStatus, field_group, field_label, field_reason,
                                 field_sort_key, field_status)


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    model_id: str
    prompt_version: str
    temperature: Decimal
    config_hash: str
    input_hash: str


@dataclass(frozen=True)
class ServedField:
    field_path: str
    value: object
    element_ids: list[uuid.UUID]
    quote: str


@dataclass(frozen=True)
class ServedTerms:
    version_id: uuid.UUID
    run_id: uuid.UUID
    fields: dict[str, ServedField]
    unserved: list[str]


# A real review, or a demo guest's own (spec P2+P9). Both expose field_path, decision, corrected_value, reason,
# decided_by and decided_at.
Review = FieldReview | GuestFieldReview


def _reviews_by_field(session: Session, run_id: uuid.UUID, overlay_guest: uuid.UUID | None) -> dict[str, Review]:
    """The run's real reviews, plus the guest's own when a guest is given. A guest can only decide a field that has
    no real review (record_review), so the two never overlap."""
    reviews: dict[str, Review] = {
        r.field_path: r for r in session.scalars(select(FieldReview).where(FieldReview.run_id == run_id))
    }
    if overlay_guest is not None:
        reviews |= {r.field_path: r for r in session.scalars(select(GuestFieldReview).where(
            GuestFieldReview.run_id == run_id, GuestFieldReview.guest_id == overlay_guest))}
    return reviews


def save_run(session: Session, version_id: uuid.UUID, config: RunConfig, raw_output: dict, results: Sequence[FieldResult], run_id: uuid.UUID | None = None) -> ExtractionRun:
    run = ExtractionRun(version_id=version_id, schema_version=config.schema_version, model_id=config.model_id,
                        prompt_version=config.prompt_version, temperature=config.temperature,
                        config_hash=config.config_hash, input_hash=config.input_hash, raw_output=raw_output)
    if run_id is not None:
        run.id = run_id
    session.add(run)
    session.flush()
    session.add_all(ExtractedField(
        run_id=run.id, field_path=r.field_path, value=r.value, element_ids=r.element_ids, quote=r.quote,
        grounded=r.grounded, validator_errors=r.validator_errors, page_grade=r.page_grade, routing=r.routing,
    ) for r in results)
    return run


def served_fields(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> ServedTerms | None:
    if documents_dao.find_document(session, tenant_id, document_id) is None:
        return None
    version_id = documents_dao.current_version_id(session, document_id)
    run = _latest_run(session, version_id)
    if run is None:
        return None
    reviews = _reviews_by_field(session, run.id, overlay_guest)
    served, unserved = {}, []
    for field in session.scalars(select(ExtractedField).where(ExtractedField.run_id == run.id).order_by(ExtractedField.field_path)):
        review = reviews.get(field.field_path)
        status = field_status(field.routing, None if review is None else review.decision)
        if status in SERVED_STATUSES:
            value = review.corrected_value if status == "corrected" else field.value
            served[field.field_path] = ServedField(field.field_path, value, field.element_ids, field.quote)
        else:
            unserved.append(field.field_path)
    return ServedTerms(version_id, run.id, served, unserved)


def runs_with_reviews(session: Session, document_id: uuid.UUID, overlay_guest: uuid.UUID | None = None
                      ) -> list[tuple[ExtractionRun, list[Review]]]:
    runs = session.scalars(
        select(ExtractionRun).join(DocumentVersion, DocumentVersion.id == ExtractionRun.version_id)
        .where(DocumentVersion.document_id == document_id).order_by(ExtractionRun.created_at)
    ).all()
    return [(run, list(_reviews_by_field(session, run.id, overlay_guest).values())) for run in runs]


def accepted_count(session: Session, run_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(ExtractedField).where(
        ExtractedField.run_id == run_id, ExtractedField.routing == FieldRouting.accepted))


@dataclass(frozen=True)
class PendingField:
    run_id: uuid.UUID
    field_path: str
    value: object
    quote: str
    grounded: bool
    validator_errors: list[str]
    page_grade: str
    document_id: uuid.UUID
    document_title: str
    version: int
    page: int | None


def _latest_run(session: Session, version_id: uuid.UUID) -> ExtractionRun | None:
    return session.scalars(
        select(ExtractionRun).where(ExtractionRun.version_id == version_id).order_by(ExtractionRun.created_at.desc())
    ).first()


def pending_reviews(session: Session, tenant_id: uuid.UUID, overlay_guest: uuid.UUID | None = None) -> list[PendingField]:
    # ponytail: a few queries per contract; fine for a demo corpus, one joined query when it isn't
    pending: list[PendingField] = []
    for row in documents_dao.list_documents(session, tenant_id):
        run = _latest_run(session, row.version.id)
        if run is None:
            continue
        reviewed = set(_reviews_by_field(session, run.id, overlay_guest))
        fields = session.scalars(
            select(ExtractedField)
            .where(ExtractedField.run_id == run.id, ExtractedField.routing == FieldRouting.needs_review)
            .order_by(ExtractedField.field_path)
        )
        pending += [
            PendingField(run.id, f.field_path, f.value, f.quote, f.grounded, list(f.validator_errors), f.page_grade,
                         row.document.id, row.document.title, row.version.version,
                         documents_dao.first_page(session, f.element_ids))
            for f in fields
            if f.field_path not in reviewed
        ]
    return pending


def record_review(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    field_path: str,
    decision: ReviewDecision,
    corrected_value: object | None,
    reason: str | None,
    decided_by: str,
    overlay_guest: uuid.UUID | None = None,
) -> Review:
    if (decision is ReviewDecision.corrected) != (corrected_value is not None):
        raise ReviewInvalid("A corrected value is required for 'corrected' and not allowed for other decisions.")
    field = session.get(ExtractedField, (run_id, field_path))
    run = session.get(ExtractionRun, run_id) if field is not None else None
    if run is None or documents_dao.get_document_for_version(session, run.version_id).tenant_id != tenant_id:
        raise FieldNotFound(f"Field {field_path} of extraction run {run_id} does not exist.")
    if overlay_guest is not None:
        return _record_guest_review(session, run_id=run_id, field_path=field_path, decision=decision,
                                    corrected_value=corrected_value, reason=reason, guest_id=overlay_guest)
    review = FieldReview(run_id=run_id, field_path=field_path, decision=decision, corrected_value=corrected_value,
                         decided_by=decided_by, reason=reason)
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:  # the primary key allows one decision per field
        session.rollback()
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.") from exc
    return review


def _record_guest_review(
    session: Session, *, run_id: uuid.UUID, field_path: str, decision: ReviewDecision, corrected_value: object | None,
    reason: str | None, guest_id: uuid.UUID,
) -> GuestFieldReview:
    """Demo mode: the decision goes to the guest's overlay. Final, like a real review: one per guest and field, and
    never on a field that already has a real review."""
    if session.get(FieldReview, (run_id, field_path)) is not None:
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.")
    review = GuestFieldReview(guest_id=guest_id, run_id=run_id, field_path=field_path, decision=decision,
                              corrected_value=corrected_value, reason=reason)
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:  # the primary key allows one decision per guest and field
        session.rollback()
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.") from exc
    return review

@dataclass(frozen=True)
class TermField:
    path: str
    label: str
    group: str
    value: object
    status: FieldStatus
    reason: str | None
    page: int | None
    quote: str  # tokenised; the route reveals it for display


@dataclass(frozen=True)
class ScheduleView:
    version: int
    method: str
    tiers: list[dict]
    valid_from: date | None


@dataclass(frozen=True)
class TermsView:
    document_id: uuid.UUID
    title: str
    version: int
    run_id: uuid.UUID | None
    extracted_at: datetime | None
    fields: list[TermField]
    household: tuple[uuid.UUID, str] | None
    schedule: ScheduleView | None
    coming_soon: tuple[str, ...] = COMING_SOON


def _schedule_in_effect(session: Session, household_id: uuid.UUID, on: date) -> ScheduleView | None:
    try:
        _schedule, version, tiers = billing_dao.schedule_in_effect(session, household_id, on)
    except NoScheduleAssigned:
        return None
    return ScheduleView(version.version, version.method.value,
                        [{"up_to_minor": t.up_to_minor, "rate_bps": str(t.rate_bps)} for t in tiers],
                        version.valid_during.lower)


def terms_view(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, on: date, overlay_guest: uuid.UUID | None = None) -> TermsView | None:
    """None = unknown document. A document without an extraction yet has run_id None and no fields."""
    document = documents_dao.find_document(session, tenant_id, document_id)
    if document is None:
        return None
    version_id = documents_dao.current_version_id(session, document_id)
    version_no = documents_dao.version_number(session, version_id)
    household = None
    schedule = None
    if document.household_id is not None and (row := billing_dao.find_household(session, tenant_id, document.household_id)):
        household = (row.id, row.name)
        schedule = _schedule_in_effect(session, row.id, on)
    run = _latest_run(session, version_id)
    if run is None:
        return TermsView(document_id, document.title, version_no, None, None, [], household, schedule)
    reviews = _reviews_by_field(session, run.id, overlay_guest)
    fields = []
    for f in sorted(session.scalars(select(ExtractedField).where(ExtractedField.run_id == run.id)),
                    key=lambda f: field_sort_key(f.field_path)):
        review = reviews.get(f.field_path)
        status = field_status(f.routing, None if review is None else review.decision)
        fields.append(TermField(
            path=f.field_path, label=field_label(f.field_path), group=field_group(f.field_path),
            value=review.corrected_value if status == "corrected" else f.value, status=status,
            reason=field_reason(status, f.grounded, list(f.validator_errors), f.page_grade,
                                None if review is None else review.reason),
            page=documents_dao.first_page(session, f.element_ids), quote=f.quote,
        ))
    return TermsView(document_id, document.title, version_no, run.id, run.created_at, fields, household, schedule)


def purge_guest_reviews(session: Session, guest_ids: Sequence[uuid.UUID]) -> None:
    """Delete these guests' overlay reviews (the 24-hour purge). The caller commits."""
    session.execute(delete(GuestFieldReview).where(GuestFieldReview.guest_id.in_(guest_ids)))
