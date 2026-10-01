import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import sessionmaker

from app import config
from app.assistant.service import AssistantRuntime, run_turn
from app.deps import get_guest_id, get_overlay_guest, get_tenant_id, limit_chat
from app.documents import dao as documents_dao
from app.documents.errors import DocumentNotFound
from app.ledger.db import SessionLocal

router = APIRouter(prefix="/chat", tags=["assistant"])


def get_assistant_runtime() -> AssistantRuntime:
    from app.assistant.runtime import get_runtime  # imported lazily: tests never build real clients
    return get_runtime()


def get_session_factory() -> sessionmaker:
    return SessionLocal


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    document_id: uuid.UUID | None = None


@router.post("", dependencies=[Depends(limit_chat)])
async def chat(
    body: ChatIn,
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)],
    overlay_guest: Annotated[uuid.UUID | None, Depends(get_overlay_guest)],
    runtime: Annotated[AssistantRuntime, Depends(get_assistant_runtime)],
    session_factory: Annotated[sessionmaker, Depends(get_session_factory)],
) -> StreamingResponse:
    if body.document_id is not None:
        with session_factory() as session:
            if documents_dao.find_document(session, tenant_id, body.document_id) is None:
                raise DocumentNotFound(f"Document {body.document_id} does not exist.")

    async def stream() -> AsyncIterator[str]:
        async for event in run_turn(session_factory=session_factory, runtime=runtime, tenant_id=tenant_id,
                                    session_id=body.session_id, message=body.message,
                                    hmac_key=config.require("PII_HMAC_KEY"), vault_key=config.require("PII_VAULT_KEY"),
                                    guest_id=guest_id, document_id=body.document_id, overlay_guest=overlay_guest):
            yield f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
