import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assistant import dao as assistant_dao
from app.assistant.overlays import purge_stale_overlays
from app.deps import get_session, get_tenant_id, parse_guest_header

router = APIRouter(prefix="/guests", tags=["assistant"])


class GuestOut(BaseModel):
    id: uuid.UUID


@router.post("", status_code=201, response_model=GuestOut)
def register_guest(
    session: Annotated[Session, Depends(get_session)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    x_guest_id: Annotated[str | None, Header()] = None,
) -> GuestOut:
    # Purge before registering: a guest returning after 24 hours idle starts from the shared data again
    # (registering would bump their last_seen_at and keep their stale decisions).
    purge_stale_overlays(session, tenant_id, datetime.now(timezone.utc))
    return GuestOut(id=assistant_dao.register_guest(session, tenant_id, parse_guest_header(x_guest_id)))
