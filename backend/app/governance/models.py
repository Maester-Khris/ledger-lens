import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Numeric, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.governance.types import ToolDecision
from app.ledger.models import Base


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    temperature: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    result_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_currency: Mapped[str | None] = mapped_column(Text, ForeignKey("currencies.code"), nullable=True)
    citation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    proposed_entries: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ToolInvocationDecision(Base):
    __tablename__ = "tool_invocation_decisions"
    __mapper_args__ = {"eager_defaults": True}

    invocation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision: Mapped[ToolDecision] = mapped_column(SAEnum(ToolDecision, name="tool_decision", native_enum=True), nullable=False)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    posting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("postings.id"), nullable=True)