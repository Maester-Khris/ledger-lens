import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.types import FieldRouting, ReviewDecision
from app.ledger.models import Base


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    schema_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.clock_timestamp())


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_runs.id"), primary_key=True)
    field_path: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[object] = mapped_column(JSONB(none_as_null=False), nullable=False)
    element_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validator_errors: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    page_grade: Mapped[str] = mapped_column(Text, nullable=False)
    routing: Mapped[FieldRouting] = mapped_column(SAEnum(FieldRouting, name="field_routing", native_enum=True), nullable=False)


class FieldReview(Base):
    __tablename__ = "field_reviews"
    __mapper_args__ = {"eager_defaults": True}
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    field_path: Mapped[str] = mapped_column(Text, primary_key=True)
    decision: Mapped[ReviewDecision] = mapped_column(SAEnum(ReviewDecision, name="review_decision", native_enum=True), nullable=False)
    corrected_value: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
