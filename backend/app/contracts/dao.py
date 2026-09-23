import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

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


def save_run(session: Session, version_id: uuid.UUID, config: RunConfig, raw_output: dict, results: Sequence[FieldResult]) -> ExtractionRun:
    run = ExtractionRun(version_id=version_id, schema_version=config.schema_version, model_id=config.model_id,
                        prompt_version=config.prompt_version, temperature=config.temperature,
                        config_hash=config.config_hash, input_hash=config.input_hash, raw_output=raw_output)
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
    run = session.scalars(
        select(ExtractionRun).where(ExtractionRun.version_id == version_id).order_by(ExtractionRun.created_at.desc())
    ).first()
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
