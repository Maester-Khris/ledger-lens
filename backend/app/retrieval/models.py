import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.ledger.models import Base


class ElementSearch(Base):
    __tablename__ = "element_search"
    element_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_elements.id"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    tsv: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
