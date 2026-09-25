import enum
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.ledger.models import Base


class ChatOutcome(str, enum.Enum):
    answered = "answered"
    refused = "refused"
    timed_out = "timed_out"
    cancelled = "cancelled"
    error = "error"


class ChatTurn(Base):
    __tablename__ = "chat_turns"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    question_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    answer_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False)
    retrieved: Mapped[list] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[ChatOutcome] = mapped_column(SAEnum(ChatOutcome, name="chat_outcome", native_enum=True), nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    graph_version: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
