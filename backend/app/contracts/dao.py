import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.errors import FieldAlreadyReviewed, FieldNotFound, ReviewInvalid
from app.contracts.fields import FieldResult
from app.contracts.models import ExtractedField, ExtractionRun, FieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from app.documents import dao as documents_dao


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


def served_fields(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> ServedTerms | None:
    if documents_dao.find_document(session, tenant_id, document_id) is None:
        return None
    version_id = documents_dao.current_version_id(session, document_id)
    run = _latest_run(session, version_id)
    if run is None:
        return None
    reviews = {r.field_path: r for r in session.scalars(select(FieldReview).where(FieldReview.run_id == run.id))}
    served, unserved = {}, []
    for field in session.scalars(select(ExtractedField).where(ExtractedField.run_id == run.id).order_by(ExtractedField.field_path)):
        review = reviews.get(field.field_path)
        if review is not None and review.decision is ReviewDecision.corrected:
            served[field.field_path] = ServedField(field.field_path, review.corrected_value, field.element_ids, field.quote)
        elif (review is not None and review.decision is ReviewDecision.confirmed) or (
            review is None and field.routing is FieldRouting.accepted
        ):
            served[field.field_path] = ServedField(field.field_path, field.value, field.element_ids, field.quote)
        else:
            unserved.append(field.field_path)
    return ServedTerms(version_id, run.id, served, unserved)


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


def pending_reviews(session: Session, tenant_id: uuid.UUID) -> list[PendingField]:
    # ponytail: a few queries per contract; fine for a demo corpus, one joined query when it isn't
    pending: list[PendingField] = []
    for row in documents_dao.list_documents(session, tenant_id):
        run = _latest_run(session, row.version.id)
        if run is None:
            continue
        reviewed = set(session.scalars(select(FieldReview.field_path).where(FieldReview.run_id == run.id)))
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
) -> FieldReview:
    if (decision is ReviewDecision.corrected) != (corrected_value is not None):
        raise ReviewInvalid("A corrected value is required for 'corrected' and not allowed for other decisions.")
    field = session.get(ExtractedField, (run_id, field_path))
    run = session.get(ExtractionRun, run_id) if field is not None else None
    if run is None or documents_dao.get_document_for_version(session, run.version_id).tenant_id != tenant_id:
        raise FieldNotFound(f"Field {field_path} of extraction run {run_id} does not exist.")
    review = FieldReview(run_id=run_id, field_path=field_path, decision=decision, corrected_value=corrected_value,
                         decided_by=decided_by, reason=reason)
    session.add(review)
    try:
        session.commit()
    except IntegrityError as exc:  # the primary key allows one decision per field
        session.rollback()
        raise FieldAlreadyReviewed(f"Field {field_path} of extraction run {run_id} has already been reviewed.") from exc
    return review
