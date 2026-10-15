from decimal import Decimal

import pytest

from app.billing.fee_math import Tier
from app.contracts.fee_text import FeeBand, FeeTextError, parse_amount_minor, parse_rate_bps, tiers_from_bands

M = 1_000_000 * 100  # one million, in minor units


@pytest.mark.parametrize(("text", "bps"), [("0.975%", "97.5"), ("1.10%", "110"), ("0.85 %", "85"), ("5 bps", "5"), ("2.5 basis points", "2.5")])
def test_rates(text, bps):
    assert parse_rate_bps(text) == Decimal(bps)


@pytest.mark.parametrize(("text", "minor"), [
    ("First $500 million", 500 * M), ("on the next $1.5 billion", 1500 * M), ("On the first $1,000,000", 1 * M),
    ("in excess of $26 billion", 26_000 * M), ("On amounts thereafter", None),
])
def test_amounts(text, minor):
    assert parse_amount_minor(text) == minor


def test_nomura_schedule():
    bands = [FeeBand("on the first $500 million", "0.55%"), FeeBand("on the next $500 million", "0.50%"),
             FeeBand("on the next $1.5 billion", "0.45%"), FeeBand("on assets in excess of $2.5 billion", "0.425%")]
    assert tiers_from_bands(bands) == (Tier(500 * M, Decimal("55")), Tier(1000 * M, Decimal("50")),
                                       Tier(2500 * M, Decimal("45")), Tier(None, Decimal("42.5")))


def test_aim_schedule_with_thereafter():
    bands = [FeeBand("First $500 million", "0.975%"), FeeBand("Next $500 million", "0.95%"),
             FeeBand("Next $500 million", "0.925%"), FeeBand("On amounts thereafter", "0.90%")]
    assert tiers_from_bands(bands)[-2:] == (Tier(1500 * M, Decimal("92.5")), Tier(None, Decimal("90")))


def test_calamos_schedule_sums_to_the_excess_threshold():
    bands = [FeeBand("of the first $500 million", "1.10%"), FeeBand("of the next $500 million", "1.05%")]
    bands += [FeeBand("of the next $5 billion", rate) for rate in ("1.00%", "0.98%", "0.96%", "0.94%", "0.92%")]
    bands += [FeeBand("in excess of $26 billion", "0.90%")]
    assert tiers_from_bands(bands)[-2:] == (Tier(26_000 * M, Decimal("92")), Tier(None, Decimal("90")))


def test_tremblay_schedule():
    bands = [FeeBand("On the first $1,000,000", "1.00%"), FeeBand("On the next $1,500,000", "0.85%"),
             FeeBand("On assets in excess of $2,500,000", "0.65%")]
    assert tiers_from_bands(bands) == (Tier(1 * M, Decimal("100")), Tier(int(2.5 * M), Decimal("85")), Tier(None, Decimal("65")))


def test_excess_threshold_must_match_the_bands():
    bands = [FeeBand("first $500 million", "0.5%"), FeeBand("in excess of $600 million", "0.4%")]
    with pytest.raises(FeeTextError, match="add up to"):
        tiers_from_bands(bands)


@pytest.mark.parametrize(("bands", "message"), [
    ([FeeBand("first $500 million", "0.5%")], "open-ended"),
    ([FeeBand("next $500 million", "0.5%"), FeeBand("thereafter", "0.4%")], "must start"),
    ([FeeBand("first $500 million", "0.5%"), FeeBand("thereafter", "0.4%"), FeeBand("next $1 billion", "0.3%")], "last"),
    ([FeeBand("first $500 million", "half a percent"), FeeBand("thereafter", "0.4%")], "rate"),
    ([FeeBand("first tranche", "0.5%"), FeeBand("thereafter", "0.4%")], "amount"),
    ([], "no fee bands"),
])
def test_malformed_schedules(bands, message):
    with pytest.raises(FeeTextError, match=message):
        tiers_from_bands(bands)
