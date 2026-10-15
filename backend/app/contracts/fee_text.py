"""Contract fee wording -> billing tiers. The model copies wording verbatim; this code does the units
and the running totals, so no number in a tier ever comes from model arithmetic."""
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.billing.fee_math import Tier

MINOR_UNITS_PER_UNIT = 100  # USD and CAD both have two decimals
BPS_PER_PERCENT = Decimal(100)
SCALES = {"thousand": Decimal(1_000), "million": Decimal(1_000_000), "billion": Decimal(1_000_000_000)}
_AMOUNT = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*(thousand|million|billion)?", re.I)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_BPS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:bps|bp|basis points?)\b", re.I)
_OPEN = re.compile(r"\b(in excess of|excess over|over|above|thereafter)\b", re.I)


class FeeTextError(ValueError):
    pass


@dataclass(frozen=True)
class FeeBand:
    band_text: str
    rate_text: str


def parse_rate_bps(rate_text: str) -> Decimal:
    try:
        if match := _PERCENT.search(rate_text):
            return Decimal(match.group(1)) * BPS_PER_PERCENT
        if match := _BPS.search(rate_text):
            return Decimal(match.group(1))
    except InvalidOperation:
        pass
    raise FeeTextError(f"no rate found in {rate_text!r}")


def parse_amount_minor(text: str) -> int | None:
    match = _AMOUNT.search(text)
    if match is None:
        return None
    units = Decimal(match.group(1).replace(",", "")) * SCALES.get((match.group(2) or "").lower(), Decimal(1))
    return int(units * MINOR_UNITS_PER_UNIT)


def tiers_from_bands(bands: Sequence[FeeBand]) -> tuple[Tier, ...]:
    if not bands:
        raise FeeTextError("no fee bands")
    tiers: list[Tier] = []
    cumulative = 0
    for index, band in enumerate(bands):
        wording = band.band_text.lower()
        amount = parse_amount_minor(band.band_text)
        rate = parse_rate_bps(band.rate_text)
        if tiers and tiers[-1].up_to_minor is None:
            raise FeeTextError("an open-ended band must be the last one")
        if _OPEN.search(wording):
            if amount is not None and amount != cumulative:
                raise FeeTextError(f"band {band.band_text!r} starts at {amount} but the bands above add up to {cumulative}")
            tiers.append(Tier(None, rate))
            continue
        if amount is None:
            raise FeeTextError(f"no amount in band {band.band_text!r}")
        if "first" in wording:
            if index != 0:
                raise FeeTextError("only the first band may say 'first'")
            cumulative = amount
        elif "next" in wording:
            if index == 0:
                raise FeeTextError("the schedule must start with a 'first' band")
            cumulative += amount
        else:
            raise FeeTextError(f"unrecognised band wording {band.band_text!r}")
        tiers.append(Tier(cumulative, rate))
    if tiers[-1].up_to_minor is not None:
        raise FeeTextError("the last band must be open-ended (in excess of / thereafter)")
    return tuple(tiers)
