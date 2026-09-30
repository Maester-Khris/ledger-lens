import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.assistant import dao as assistant_dao
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
    return GuestOut(id=assistant_dao.register_guest(session, tenant_id, parse_guest_header(x_guest_id)))
