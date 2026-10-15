
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, Text, TIMESTAMP, Date, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, UUID, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.billing.types import FeeMethod
from app.ledger.models import Base

_fee_method = SAEnum(FeeMethod, name="fee_method", native_enum=True)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _created_at() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Household(Base):
    __tablename__ = "households"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Client(Base):
    __tablename__ = "clients"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class ClientAccount(Base):
    __tablename__ = "client_accounts"
    __mapper_args__ = {"eager_defaults": True}
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    linked_on: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class AccountValuation(Base):
    __tablename__ = "account_valuations"
    __mapper_args__ = {"eager_defaults": True}
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, primary_key=True)
    market_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeSchedule(Base):
    __tablename__ = "fee_schedules"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    revenue_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeScheduleVersion(Base):
    # Database primary key is (schedule_id, valid_during WITHOUT OVERLAPS); the ORM
    # identifies rows by the equally unique (schedule_id, version).
    __tablename__ = "fee_schedule_versions"
    __mapper_args__ = {"eager_defaults": True}
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fee_schedules.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    method: Mapped[FeeMethod] = mapped_column(_fee_method, nullable=False)
    valid_during: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeScheduleTier(Base):
    __tablename__ = "fee_schedule_tiers"
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    tier_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    up_to_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rate_bps: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)


class HouseholdFeeAssignment(Base):
    __tablename__ = "household_fee_assignments"
    __mapper_args__ = {"eager_defaults": True}
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), primary_key=True)
    valid_during: Mapped[Range[date]] = mapped_column(DATERANGE, primary_key=True)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("fee_schedules.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class FeeCalculation(Base):
    __tablename__ = "fee_calculations"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    period: Mapped[Range[date]] = mapped_column(DATERANGE, nullable=False)
    schedule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[FeeMethod] = mapped_column(_fee_method, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    household_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    period_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allocations: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rounding_remainder_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posting_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("postings.id"), nullable=False)
    created_at: Mapped[datetime] = _created_at()
