import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import config
from app.deps import DECIDED_BY, get_session, get_tenant_id
from app.documents import dao, store
from app.documents.sniff import MAX_UPLOAD_BYTES, inspect_pdf
from app.ingestion_pipeline import PIPELINE, version_status

router = APIRouter(prefix="/documents", tags=["documents"])
SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]
PREVIEW_ELEMENTS = 5
DOCUMENT_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{1,63}$"


class UploadOut(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    status_url: str


class EventOut(BaseModel):
    stage: str
    at: datetime
    detail: dict


class DocumentOut(BaseModel):
    id: uuid.UUID
    document_key: str
    title: str
    source_url: str | None
    household_id: uuid.UUID | None
    version: int
    version_id: uuid.UUID
    page_count: int
    byte_size: int
    file_sha256: str
    uploaded_at: datetime
    element_count: int
    status: Literal["processing", "ready", "failed"]
    status_note: str | None
    events: list[EventOut]


class ElementPreviewOut(BaseModel):
    ordinal: int
    kind: str
    section_path: list[str]
    page_start: int
    page_end: int
    text: str


class DocumentDetailOut(DocumentOut):
    preview: list[ElementPreviewOut]


def _out(row: dao.DocumentRow) -> dict:
    status = version_status(PIPELINE, row.events)
    return dict(
        id=row.document.id, document_key=row.document.document_key, title=row.document.title,
        source_url=row.document.source_url, household_id=row.document.household_id, version=row.version.version, version_id=row.version.id,
        page_count=row.version.page_count, byte_size=row.version.byte_size, file_sha256=row.version.file_sha256,
        uploaded_at=row.version.created_at, element_count=row.element_count, status=status.state,
        status_note=status.note,
        events=[EventOut(stage=e.stage.value, at=e.created_at, detail=e.detail) for e in row.events],
    )


@router.post("", status_code=202, response_model=UploadOut)
def upload_document(
    response: Response,
    session: SessionDep,
    tenant_id: TenantDep,
    file: Annotated[UploadFile, File()],
    document_key: Annotated[str, Form(pattern=DOCUMENT_KEY_PATTERN)],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    source_url: Annotated[str | None, Form(max_length=2000)] = None,
    household_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadOut:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    result = dao.register_upload(
        session, tenant_id=tenant_id, document_key=document_key, title=title, source_url=source_url,
        data=data, facts=inspect_pdf(data), uploaded_by=DECIDED_BY, store_root=config.DOCUMENT_STORE_DIR,
        household_id=household_id,
    )
    if not result.created:
        response.status_code = 200
    return UploadOut(document_id=result.document.id, version_id=result.version.id, version=result.version.version,
                     status_url=f"/documents/{result.document.id}")


@router.get("", response_model=list[DocumentOut])
def list_documents(session: SessionDep, tenant_id: TenantDep) -> list[DocumentOut]:
    return [DocumentOut(**_out(row)) for row in dao.list_documents(session, tenant_id)]


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(document_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> DocumentDetailOut:
    row = dao.get_document_row(session, tenant_id, document_id)
    elements = dao.list_elements(session, row.version.id)[:PREVIEW_ELEMENTS]
    # ponytail: detokenises for the single demo user; gate on the principal's permissions once auth exists
    texts = dao.reveal(session, tenant_id, [e.text_redacted for e in elements], config.require("PII_VAULT_KEY"))
    preview = [
        ElementPreviewOut(ordinal=e.ordinal, kind=e.kind.value, section_path=e.section_path,
                          page_start=e.page_start, page_end=e.page_end, text=text)
        for e, text in zip(elements, texts)
    ]
    return DocumentDetailOut(**_out(row), preview=preview)


@router.get("/{document_id}/versions/{version}/file")
def get_original_file(document_id: uuid.UUID, version: int, session: SessionDep, tenant_id: TenantDep) -> FileResponse:
    # ponytail: contains PII; behind the demo-user dependency only until real authorization exists
    row = dao.get_version_by_number(session, tenant_id, document_id, version)
    return FileResponse(store.original_path(config.DOCUMENT_STORE_DIR, row.file_sha256), media_type="application/pdf")
