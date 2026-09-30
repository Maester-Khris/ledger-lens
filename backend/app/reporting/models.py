import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import DATERANGE, UUID, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.ledger.models import Base


class GlExport(Base):
    __tablename__ = "gl_exports"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    period: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    currency: Mapped[str] = mapped_column(Text, ForeignKey("currencies.code"), nullable=False)
    cutoff: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_debits_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_credits_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())