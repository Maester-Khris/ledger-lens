import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Identity, Integer, LargeBinary, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.documents.types import DocumentType, ElementKind, VersionStage
from app.ledger.models import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _created_at() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    document_key: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(SAEnum(DocumentType, name="document_type", native_enum=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    household_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class VersionEvent(Base):
    __tablename__ = "version_events"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    stage: Mapped[VersionStage] = mapped_column(SAEnum(VersionStage, name="version_stage", native_enum=True), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.clock_timestamp())


class DocumentElement(Base):
    __tablename__ = "document_elements"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[ElementKind] = mapped_column(SAEnum(ElementKind, name="element_kind", native_enum=True), nullable=False)
    section_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)


class PiiToken(Base):
    __tablename__ = "pii_tokens"
    __mapper_args__ = {"eager_defaults": True}
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    token: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = _created_at()
