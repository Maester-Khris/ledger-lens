import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from app.billing.dao import get_fee_calculation, run_household_fee
from app.billing.models import FeeCalculation
from app.billing.types import FeeMethod
from app.deps import get_session, get_tenant_id
from app.ranges import range_end_inclusive
from app.routes.postings import mark_replay

router = APIRouter(tags=["billing"])

SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]


class FeeRunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    household_id: uuid.UUID
    period_start: date
    period_end: date

    @model_validator(mode="after")
    def end_not_before_start(self) -> "FeeRunIn":
        if self.period_end < self.period_start:
            raise ValueError("period_end must not be before period_start")
        return self


class FeeCalculationOut(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    period_start: date
    period_end: date
    schedule_id: uuid.UUID
    schedule_version: int
    method: FeeMethod
    household_value_minor: int
    period_fee_minor: int
    allocations: dict[str, int]
    rounding_remainder_minor: int
    posting_id: uuid.UUID
    inputs: dict
    created_at: datetime


def _out(calculation: FeeCalculation) -> FeeCalculationOut:
    return FeeCalculationOut(
        id=calculation.id,
        household_id=calculation.household_id,
        period_start=calculation.period.lower,
        period_end=range_end_inclusive(calculation.period),
        schedule_id=calculation.schedule_id,
        schedule_version=calculation.schedule_version,
        method=calculation.method,
        household_value_minor=calculation.household_value_minor,
        period_fee_minor=calculation.period_fee_minor,
        allocations=calculation.allocations,
        rounding_remainder_minor=calculation.rounding_remainder_minor,
        posting_id=calculation.posting_id,
        inputs=calculation.inputs,
        created_at=calculation.created_at,
    )


@router.post("/fee-runs", status_code=201, response_model=FeeCalculationOut)
def run_fee(body: FeeRunIn, response: Response, session: SessionDep, tenant_id: TenantDep) -> FeeCalculationOut:
    result = run_household_fee(
        session, tenant_id=tenant_id, household_id=body.household_id,
        period_start=body.period_start, period_end=body.period_end,
    )
    mark_replay(response, result.replayed)
    return _out(result.calculation)


@router.get("/fee-calculations/{calculation_id}", response_model=FeeCalculationOut)
def read_fee_calculation(calculation_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> FeeCalculationOut:
    return _out(get_fee_calculation(session, tenant_id=tenant_id, calculation_id=calculation_id))