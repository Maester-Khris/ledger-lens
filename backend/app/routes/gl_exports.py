import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.deps import get_session, get_tenant_id
from app.ranges import range_end_inclusive
from app.reporting.dao import SETTLE_MARGIN, create_gl_export, export_csv
from app.reporting.models import GlExport

router = APIRouter(prefix="/gl-exports", tags=["reporting"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


def get_settle_margin() -> timedelta:
    return SETTLE_MARGIN


class GlExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_start: date
    period_end: date
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def end_not_before_start(self) -> "GlExportIn":
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class GlExportOut(BaseModel):
    id: uuid.UUID
    period_start: date
    period_end: date
    currency: str
    cutoff: datetime
    line_count: int
    total_debits_minor: int
    total_credits_minor: int
    content_sha256: str
    created_at: datetime
    csv_url: str


def _out(export: GlExport) -> GlExportOut:
    return GlExportOut(
        id=export.id, period_start=export.period.lower, period_end=range_end_inclusive(export.period),
        currency=export.currency, cutoff=export.cutoff, line_count=export.line_count,
        total_debits_minor=export.total_debits_minor, total_credits_minor=export.total_credits_minor,
        content_sha256=export.content_sha256, created_at=export.created_at, csv_url=f"/gl-exports/{export.id}.csv",
    )


@router.post("", status_code=201, response_model=GlExportOut)
def create_export(
    body: GlExportIn,
    session: SessionDep,
    tenant_id: TenantDep,
    settle_margin: Annotated[timedelta, Depends(get_settle_margin)],
) -> GlExportOut:
    export = create_gl_export(
        session, tenant_id=tenant_id, currency=body.currency,
        period_start=body.period_start, period_end=body.period_end, settle_margin=settle_margin,
    )
    return _out(export)


@router.get("/{export_id}.csv", response_class=PlainTextResponse)
def download_export(export_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> PlainTextResponse:
    export, content = export_csv(session, tenant_id=tenant_id, export_id=export_id)
    return PlainTextResponse(
        content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="gl-export-{export.id}.csv"',
            "X-Content-SHA256": export.content_sha256,
        },
    )