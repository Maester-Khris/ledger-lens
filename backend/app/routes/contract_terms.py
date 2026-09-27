import uuid
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import config
from app.contracts import dao as contracts_dao
from app.deps import get_session, get_tenant_id
from app.documents import dao as documents_dao
from app.documents.errors import DocumentNotFound

router = APIRouter(prefix="/documents", tags=["contracts"])


class TermFieldOut(BaseModel):
    path: str
    label: str
    group: str
    value: object
    status: str
    reason: str | None
    page: int | None
    quote: str


class ExtractionOut(BaseModel):
    run_id: uuid.UUID
    extracted_at: datetime
    fields: list[TermFieldOut]


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str


class ScheduleOut(BaseModel):
    version: int
    method: str
    tiers: list[dict]
    valid_from: date | None


class TermsOut(BaseModel):
    document_id: uuid.UUID
    title: str
    version: int
    extraction: ExtractionOut | None
    household: HouseholdOut | None
    billing_schedule: ScheduleOut | None
    coming_soon: list[str]


@router.get("/{document_id}/terms", response_model=TermsOut)
def get_terms(document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)],
              tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)]) -> TermsOut:
    view = contracts_dao.terms_view(session, tenant_id, document_id, date.today())
    if view is None:
        raise DocumentNotFound(f"Document {document_id} does not exist.")
    # ponytail: detokenises for the single demo user, like the document preview; gate on permissions once auth exists
    quotes = documents_dao.reveal(session, tenant_id, [f.quote for f in view.fields], config.require("PII_VAULT_KEY"))
    fields = [TermFieldOut(**(asdict(f) | {"quote": q})) for f, q in zip(view.fields, quotes)]
    return TermsOut(
        document_id=view.document_id, title=view.title, version=view.version,
        extraction=None if view.run_id is None else ExtractionOut(run_id=view.run_id, extracted_at=view.extracted_at, fields=fields),
        household=None if view.household is None else HouseholdOut(id=view.household[0], name=view.household[1]),
        billing_schedule=None if view.schedule is None else ScheduleOut(**asdict(view.schedule)),
        coming_soon=list(view.coming_soon),
    )
