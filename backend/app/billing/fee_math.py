import calendar
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from fractions import Fraction

from app.billing.types import FeeMethod

BPS_PER_UNIT = Decimal(10_000)


@dataclass(frozen=True)
class Tier:
    up_to_minor: int | None  # inclusive upper bound in minor units; None = no upper limit
    rate_bps: Decimal  # annual rate in basis points (100 bps = 1%)


@dataclass(frozen=True)
class AccountValue:
    account_id: uuid.UUID
    value_minor: int  # period-end market value
    linked_on: date


@dataclass(frozen=True)
class FeeInputs:
    period_start: date
    period_end: date  # inclusive
    method: FeeMethod
    tiers: tuple[Tier, ...]
    accounts: tuple[AccountValue, ...]


@dataclass(frozen=True)
class FeeResult:
    household_value_minor: int
    annual_fee: Decimal
    period_fee_minor: int
    allocations: dict[uuid.UUID, int]
    rounding_remainder_minor: int


def validate_tiers(tiers: Sequence[Tier]) -> None:
    if not tiers:
        raise ValueError("a fee schedule needs at least one tier")
    if tiers[-1].up_to_minor is not None:
        raise ValueError("the last tier must have no upper limit")
    caps = [tier.up_to_minor for tier in tiers[:-1]]
    if any(cap is None for cap in caps):
        raise ValueError("only the last tier may have no upper limit")
    if any(cap <= 0 for cap in caps) or caps != sorted(set(caps)):
        raise ValueError("tier upper limits must be positive and strictly ascending")
    if any(tier.rate_bps < 0 for tier in tiers):
        raise ValueError("tier rates must not be negative")


def _rate(rate_bps: Decimal) -> Decimal:
    return rate_bps / BPS_PER_UNIT


def annual_fee(value_minor: int, tiers: Sequence[Tier], method: FeeMethod) -> Decimal:
    validate_tiers(tiers)
    value = Decimal(value_minor)
    if method is FeeMethod.cliff:
        tier = next(t for t in tiers if t.up_to_minor is None or value_minor <= t.up_to_minor)
        return value * _rate(tier.rate_bps)
    fee, lower = Decimal(0), Decimal(0)
    for tier in tiers:
        upper = value if tier.up_to_minor is None else min(value, Decimal(tier.up_to_minor))
        if upper <= lower:
            break
        fee += (upper - lower) * _rate(tier.rate_bps)
        lower = upper
    return fee


def days_in_period(start: date, end: date) -> int:
    if end < start:
        raise ValueError(f"period end {end} is before period start {start}")
    return (end - start).days + 1


def period_fraction(start: date, end: date) -> Decimal:
    year_days = 366 if calendar.isleap(end.year) else 365
    return Decimal(days_in_period(start, end)) / Decimal(year_days)


def linked_fraction(linked_on: date, start: date, end: date) -> Decimal:
    if linked_on > end:
        return Decimal(0)
    first_day = max(start, linked_on)
    return Decimal((end - first_day).days + 1) / Decimal(days_in_period(start, end))


def round_half_even(amount: Decimal) -> int:
    return int(amount.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def allocate(total_minor: int, weights: Mapping[uuid.UUID, Decimal]) -> tuple[dict[uuid.UUID, int], int]:
    """Split total_minor by weight: floor each share, then hand the leftover minor units
    to the largest fractional remainders (ties broken by account id).

    Uses exact rational arithmetic: Decimal rounding at 28 digits can turn an exact
    integer share into x.999..., and flooring that loses a cent.
    """
    if total_minor == 0:
        return {key: 0 for key in weights}, 0
    weight_sum = sum((Fraction(weight) for weight in weights.values()), Fraction(0))
    if weight_sum <= 0:
        raise ValueError("cannot allocate a positive total with no positive weight")
    exact = {key: Fraction(total_minor) * Fraction(weight) / weight_sum for key, weight in weights.items()}
    floors = {key: math.floor(share) for key, share in exact.items()}
    remainder = total_minor - sum(floors.values())
    by_largest_remainder = sorted(exact, key=lambda key: (-(exact[key] - floors[key]), str(key)))
    for key in by_largest_remainder[:remainder]:
        floors[key] += 1
    return floors, remainder


def calculate_household_fee(inputs: FeeInputs) -> FeeResult:
    if any(account.value_minor < 0 for account in inputs.accounts):
        raise ValueError("account values must not be negative")
    household_value = sum(account.value_minor for account in inputs.accounts)
    yearly = annual_fee(household_value, inputs.tiers, inputs.method)
    period_fee_exact = yearly * period_fraction(inputs.period_start, inputs.period_end)

    per_account_exact = {
        account.account_id: (
            Decimal(0)
            if household_value == 0
            else period_fee_exact
            * Decimal(account.value_minor)
            / Decimal(household_value)
            * linked_fraction(account.linked_on, inputs.period_start, inputs.period_end)
        )
        for account in inputs.accounts
    }
    period_fee_minor = round_half_even(sum(per_account_exact.values(), Decimal(0)))
    allocations, remainder = allocate(period_fee_minor, per_account_exact)
    return FeeResult(
        household_value_minor=household_value,
        annual_fee=yearly,
        period_fee_minor=period_fee_minor,
        allocations=allocations,
        rounding_remainder_minor=remainder,
    )


def inputs_to_json(inputs: FeeInputs, *, schedule_id: uuid.UUID, schedule_version: int) -> dict:
    return {
        "period": {"start": inputs.period_start.isoformat(), "end": inputs.period_end.isoformat()},
        "schedule": {
            "id": str(schedule_id),
            "version": schedule_version,
            "method": inputs.method.value,
            "tiers": [{"up_to_minor": t.up_to_minor, "rate_bps": str(t.rate_bps)} for t in inputs.tiers],
        },
        "accounts": [
            {"account_id": str(a.account_id), "value_minor": a.value_minor, "linked_on": a.linked_on.isoformat()}
            for a in inputs.accounts
        ],
    }


def inputs_from_json(data: Mapping) -> FeeInputs:
    schedule = data["schedule"]
    return FeeInputs(
        period_start=date.fromisoformat(data["period"]["start"]),
        period_end=date.fromisoformat(data["period"]["end"]),
        method=FeeMethod(schedule["method"]),
        tiers=tuple(Tier(t["up_to_minor"], Decimal(t["rate_bps"])) for t in schedule["tiers"]),
        accounts=tuple(
            AccountValue(uuid.UUID(a["account_id"]), a["value_minor"], date.fromisoformat(a["linked_on"]))
            for a in data["accounts"]
        ),
    )
