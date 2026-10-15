import random
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.billing.fee_math import (
    AccountValue,
    FeeInputs,
    Tier,
    allocate,
    annual_fee,
    calculate_household_fee,
    inputs_from_json,
    inputs_to_json,
    linked_fraction,
    period_fraction,
    round_half_even,
    validate_tiers,
)
from app.billing.types import FeeMethod

TIERS = (
    Tier(up_to_minor=100_000_000, rate_bps=Decimal("100")),
    Tier(up_to_minor=250_000_000, rate_bps=Decimal("80")),
    Tier(up_to_minor=None, rate_bps=Decimal("65")),
)
A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
C = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
Q3_START, Q3_END = date(2026, 7, 1), date(2026, 9, 30)  # 92 days, 2026 is not a leap year


@pytest.mark.parametrize(
    ("value", "graduated", "cliff"),
    [
        (180_000_000, Decimal("1640000"), Decimal("1440000")),
        (100_000_000, Decimal("1000000"), Decimal("1000000")),  # exactly on the boundary: tier 1 rate
        (100_000_001, Decimal("1000000.008"), Decimal("800000.008")),  # one cent over: cliff drops the rate
        (300_000_000, Decimal("2525000"), Decimal("1950000")),
        (0, Decimal("0"), Decimal("0")),
    ],
)
def test_annual_fee_graduated_vs_cliff(value, graduated, cliff):
    assert annual_fee(value, TIERS, FeeMethod.graduated) == graduated
    assert annual_fee(value, TIERS, FeeMethod.cliff) == cliff


@pytest.mark.parametrize(
    "tiers",
    [
        (),
        (Tier(100, Decimal("1")), Tier(50, Decimal("1")), Tier(None, Decimal("1"))),  # caps not ascending
        (Tier(None, Decimal("1")), Tier(100, Decimal("1"))),  # open-ended tier not last
        (Tier(100, Decimal("1")),),  # no open-ended final tier
        (Tier(None, Decimal("-1")),),  # negative rate
    ],
)
def test_invalid_tier_tables_are_rejected(tiers):
    with pytest.raises(ValueError):
        validate_tiers(tiers)


def test_period_fraction_uses_inclusive_days_over_year_length():
    assert period_fraction(Q3_START, Q3_END) == Decimal(92) / Decimal(365)
    assert period_fraction(date(2028, 1, 1), date(2028, 3, 31)) == Decimal(91) / Decimal(366)


def test_period_end_before_start_is_rejected():
    with pytest.raises(ValueError):
        period_fraction(Q3_END, Q3_START)


def test_linked_fraction_prorates_mid_period_links():
    assert linked_fraction(date(2026, 1, 1), Q3_START, Q3_END) == Decimal(1)
    assert linked_fraction(date(2026, 8, 1), Q3_START, Q3_END) == Decimal(61) / Decimal(92)
    assert linked_fraction(date(2026, 10, 1), Q3_START, Q3_END) == Decimal(0)


@pytest.mark.parametrize(("amount", "expected"), [("2.5", 2), ("3.5", 4), ("-2.5", -2), ("413369.863", 413370)])
def test_round_half_even(amount, expected):
    assert round_half_even(Decimal(amount)) == expected


def test_allocate_gives_leftover_cents_to_largest_remainders():
    allocations, remainder = allocate(10, {A: Decimal(2), B: Decimal(1)})
    assert allocations == {A: 7, B: 3} and remainder == 1  # exact shares 6.67 / 3.33


def test_allocate_breaks_exact_ties_by_account_id():
    allocations, remainder = allocate(10, {C: Decimal(1), B: Decimal(1), A: Decimal(1)})
    assert allocations == {A: 4, B: 3, C: 3} and remainder == 1


def test_allocate_zero_total_is_all_zero():
    assert allocate(0, {A: Decimal(0), B: Decimal(0)}) == ({A: 0, B: 0}, 0)


def test_household_fee_worked_example_with_proration():
    inputs = FeeInputs(
        period_start=Q3_START,
        period_end=Q3_END,
        method=FeeMethod.graduated,
        tiers=TIERS,
        accounts=(
            AccountValue(A, 120_000_000, date(2026, 1, 1)),
            AccountValue(B, 60_000_000, date(2026, 8, 1)),  # linked 61 of 92 days
        ),
    )
    result = calculate_household_fee(inputs)
    assert result.household_value_minor == 180_000_000
    assert result.annual_fee == Decimal("1640000")
    assert result.period_fee_minor == 366_941
    assert result.allocations == {A: 275_580, B: 91_361}
    assert result.rounding_remainder_minor == 1  # one leftover cent goes to the larger fractional share (B)


def test_household_fee_is_zero_when_nothing_is_linked_in_the_period():
    inputs = FeeInputs(Q3_START, Q3_END, FeeMethod.graduated, TIERS, (AccountValue(A, 50_000_000, date(2026, 10, 1)),))
    result = calculate_household_fee(inputs)
    assert result.period_fee_minor == 0 and result.allocations == {A: 0}


def test_allocations_always_sum_to_the_household_fee():
    rng = random.Random(42)
    for _ in range(1000):
        accounts = tuple(
            AccountValue(uuid.UUID(int=rng.getrandbits(128)), rng.randint(0, 5_000_000_000),
                         date(2026, rng.randint(1, 9), rng.randint(1, 28)))
            for _ in range(rng.randint(1, 5))
        )
        method = rng.choice([FeeMethod.graduated, FeeMethod.cliff])
        result = calculate_household_fee(FeeInputs(Q3_START, Q3_END, method, TIERS, accounts))
        assert sum(result.allocations.values()) == result.period_fee_minor
        assert all(v >= 0 for v in result.allocations.values())
        assert 0 <= result.rounding_remainder_minor < len(accounts)


def test_inputs_round_trip_through_json():
    inputs = FeeInputs(Q3_START, Q3_END, FeeMethod.cliff, TIERS, (AccountValue(A, 1, date(2026, 1, 1)),))
    schedule_id = uuid.uuid4()
    data = inputs_to_json(inputs, schedule_id=schedule_id, schedule_version=2)
    assert data["schedule"] == {"id": str(schedule_id), "version": 2, "method": "cliff",
                                "tiers": [{"up_to_minor": 100_000_000, "rate_bps": "100"},
                                          {"up_to_minor": 250_000_000, "rate_bps": "80"},
                                          {"up_to_minor": None, "rate_bps": "65"}]}
    assert inputs_from_json(data) == inputs
