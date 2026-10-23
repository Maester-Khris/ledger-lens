import re
import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import config
from app.contracts import dao as contracts_dao
from app.contracts.errors import FieldNotFound
from app.contracts.types import ReviewDecision
from app.deps import decided_by, get_guest_id, get_overlay_guest, get_session, get_tenant_id, require_overlay_guest
from app.documents import dao as documents_dao
from app.documents import store
from app.reporting.dashboard import invalidate_dashboard_stats

router = APIRouter(prefix="/reviews", tags=["contracts"])
SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]
OverlayGuest = Annotated[uuid.UUID | None, Depends(get_overlay_guest)]

_CROP_FIELD_PATH_PATTERN = re.compile(r"^[a-z_]+(?:\[\d+\])?$")


class VerificationOut(BaseModel):
    layer: str
    verifier: str
    read_value: Any
    outcome: str
    detail: str | None
    crop_url: str


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
    field_class: str
    verification: VerificationOut | None = None


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
def list_pending_reviews(session: SessionDep, tenant_id: TenantDep, overlay_guest: OverlayGuest) -> list[ReviewItemOut]:
    items = contracts_dao.pending_reviews(session, tenant_id, overlay_guest)
    if not items:
        return []
    vault_key = config.require("PII_VAULT_KEY")
    quotes = documents_dao.reveal(session, tenant_id, [i.quote for i in items], vault_key)

    str_v_indices = [
        idx for idx, item in enumerate(items)
        if item.verification is not None and isinstance(item.verification.read_value, str)
    ]
    revealed_v_values: dict[int, str] = {}
    if str_v_indices:
        str_texts = [items[idx].verification.read_value for idx in str_v_indices]  # type: ignore[union-attr]
        decrypted_texts = documents_dao.reveal(session, tenant_id, str_texts, vault_key)
        revealed_v_values = dict(zip(str_v_indices, decrypted_texts))

    results = []
    for idx, (item, quote) in enumerate(zip(items, quotes)):
        v_out = None
        if item.verification is not None:
            rv = revealed_v_values.get(idx, item.verification.read_value)
            v_out = VerificationOut(
                layer=item.verification.layer,
                verifier=item.verification.verifier,
                read_value=rv,
                outcome=item.verification.outcome,
                detail=item.verification.detail,
                crop_url=item.verification.crop_url,
            )
        data = asdict(item)
        data["quote"] = quote
        data["verification"] = v_out
        results.append(ReviewItemOut(**data))
    return results


@router.post("", status_code=201, response_model=ReviewOut)
def submit_review(body: ReviewIn, session: SessionDep, tenant_id: TenantDep, guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)], overlay_guest: Annotated[uuid.UUID | None, Depends(require_overlay_guest)]) -> ReviewOut:
    review = contracts_dao.record_review(
        session, tenant_id=tenant_id, run_id=body.run_id, field_path=body.field_path, decision=body.decision,
        corrected_value=body.corrected_value, reason=body.reason, decided_by=decided_by(guest_id), overlay_guest=overlay_guest,
    )
    invalidate_dashboard_stats(tenant_id)
    field_path = body.field_path if body.field_path == "fee_tiers" else review.field_path
    corrected_value = body.corrected_value if body.field_path == "fee_tiers" else review.corrected_value
    return ReviewOut(run_id=review.run_id, field_path=field_path, decision=review.decision,
                     corrected_value=corrected_value, decided_by=review.decided_by, reason=review.reason,
                     decided_at=review.decided_at)


@router.get("/{run_id}/crops/{field_path:path}")
def get_crop(
    run_id: uuid.UUID,
    field_path: str,
    session: SessionDep,
    tenant_id: TenantDep,
) -> FileResponse:
    if not _CROP_FIELD_PATH_PATTERN.match(field_path):
        raise FieldNotFound(f"Invalid crop field path: {field_path}")
    if contracts_dao.run_tenant(session, run_id) != tenant_id:
        raise FieldNotFound(f"Crop for run {run_id} not found")
    path = store.crop_path(config.DOCUMENT_STORE_DIR, run_id, field_path)
    if not path.is_file():
        raise FieldNotFound(f"Crop image {field_path} for run {run_id} does not exist")
    return FileResponse(path, media_type="image/png")
