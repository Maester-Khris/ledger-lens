import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.deps import get_overlay_guest, get_session, get_tenant_id
from app.documents.errors import DocumentNotFound
from app.reporting.timeline import document_timeline

router = APIRouter(prefix="/documents", tags=["reporting"])


class TimelineItemOut(BaseModel):
    at: datetime
    kind: str
    title: str
    detail: dict
    links: dict


@router.get("/{document_id}/timeline", response_model=list[TimelineItemOut])
def get_timeline(document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)],
                 tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
                 overlay_guest: Annotated[uuid.UUID | None, Depends(get_overlay_guest)]) -> list[TimelineItemOut]:
    items = document_timeline(session, tenant_id, document_id, overlay_guest)
    if items is None:
        raise DocumentNotFound(f"Document {document_id} does not exist.")
    return [TimelineItemOut(**asdict(item)) for item in items]
