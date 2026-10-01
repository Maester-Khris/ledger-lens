import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import config
from app.contracts import dao as contracts_dao
from app.contracts.types import ReviewDecision
from app.deps import decided_by, decisions_closed_in_demo, get_guest_id, get_session, get_tenant_id
from app.documents import dao as documents_dao
from app.reporting.dashboard import invalidate_dashboard_stats

router = APIRouter(prefix="/reviews", tags=["contracts"])
SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class ReviewItemOut(BaseModel):
    run_id: uuid.UUID
    field_path: str
    value: Any
    quote: str
    grounded: bool
    validator_errors: list[str]
    page_grade: str
    document_id: uuid.UUID
    document_title: str
    version: int
    page: int | None


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: uuid.UUID
    field_path: str = Field(min_length=1, max_length=200)
    decision: ReviewDecision
    corrected_value: Any = None
    reason: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    run_id: uuid.UUID
    field_path: str
    decision: ReviewDecision
    corrected_value: Any
    decided_by: str
    reason: str | None
    decided_at: datetime


@router.get("", response_model=list[ReviewItemOut])
def list_pending_reviews(session: SessionDep, tenant_id: TenantDep) -> list[ReviewItemOut]:
    items = contracts_dao.pending_reviews(session, tenant_id)
    if not items:
        return []
    # ponytail: detokenises for the single demo user, like the document preview; gate on permissions once auth exists
    quotes = documents_dao.reveal(session, tenant_id, [i.quote for i in items], config.require("PII_VAULT_KEY"))
    return [ReviewItemOut(**(asdict(item) | {"quote": quote})) for item, quote in zip(items, quotes)]


@router.post("", status_code=201, response_model=ReviewOut, dependencies=[Depends(decisions_closed_in_demo)])
def submit_review(body: ReviewIn, session: SessionDep, tenant_id: TenantDep, guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]) -> ReviewOut:
    review = contracts_dao.record_review(
        session, tenant_id=tenant_id, run_id=body.run_id, field_path=body.field_path, decision=body.decision,
        corrected_value=body.corrected_value, reason=body.reason, decided_by=decided_by(guest_id),
    )
    invalidate_dashboard_stats(tenant_id)
    return ReviewOut(run_id=review.run_id, field_path=review.field_path, decision=review.decision,
                     corrected_value=review.corrected_value, decided_by=review.decided_by, reason=review.reason,
                     decided_at=review.decided_at)
