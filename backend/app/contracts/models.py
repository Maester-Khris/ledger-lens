import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, Integer, Numeric, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts.types import FieldRouting, ReviewDecision
from app.demo import GUEST_DECIDED_BY
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


class GuestFieldReview(Base):
    """A demo guest's field review (spec P2+P9): private to that guest, purged after 24 hours of inactivity."""

    __tablename__ = "guest_field_reviews"
    __mapper_args__ = {"eager_defaults": True}
    guest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    field_path: Mapped[str] = mapped_column(Text, primary_key=True)
    decision: Mapped[ReviewDecision] = mapped_column(SAEnum(ReviewDecision, name="review_decision", native_enum=True), nullable=False)
    corrected_value: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    @property
    def decided_by(self) -> str:
        return GUEST_DECIDED_BY


class FieldVerification(Base):
    """One independent check of one field (X1): a local OCR re-read or a vision reading of the cited crop.
    It never changes the extracted value; a non-agree outcome only routes the field to review."""

    __tablename__ = "field_verifications"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_runs.id"), nullable=False)
    field_path: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[str] = mapped_column(SAEnum("ocr_local", "vision", name="verification_layer", native_enum=True), nullable=False)
    verifier: Mapped[str] = mapped_column(Text, nullable=False)
    crop_kind: Mapped[str] = mapped_column(SAEnum("element", "table", "page", name="crop_kind", native_enum=True), nullable=False)
    read_value: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    outcome: Mapped[str] = mapped_column(
        SAEnum("agree", "disagree", "unreadable", "error", name="verification_outcome", native_enum=True), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.clock_timestamp())


class FieldLabel(Base):
    """A ground-truth label for measuring accuracy (X1 section 10). Separate from field_reviews: measurement, not
    an operational decision."""

    __tablename__ = "field_labels"
    __mapper_args__ = {"eager_defaults": True}
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("extraction_runs.id"), primary_key=True)
    field_path: Mapped[str] = mapped_column(Text, primary_key=True)
    labeller: Mapped[str] = mapped_column(Text, primary_key=True)
    label_value: Mapped[object] = mapped_column(JSONB(none_as_null=False), nullable=False)
    blind: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
