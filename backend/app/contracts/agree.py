"""Independent verification rules for contract extraction (X1).

Extraction can be grounded in document text and still be wrong (a misread rate,
the wrong band). X1 re-reads each important field independently; these rules decide
agreement between the extracted value and the second reading. Disagreements route
fields to human review without altering the extracted value. Money fields have no
numeric tolerance: shared billing parsers evaluate values so agreement semantics
remain uniform across the system.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from difflib import SequenceMatcher
import re
from typing import Literal, cast

from app.contracts.fee_text import FeeTextError, parse_amount_minor, parse_rate_bps
from app.contracts.fields import DATE_FORMATS

Outcome = Literal["agree", "disagree", "unreadable", "error"]
TEXT_SIMILARITY = 0.9  # ponytail, a fixed cut; tuned on labels later (X1 Task 10)

_LEGAL_SUFFIXES = ("l p", "inc", "llc", "ltd", "lp", "corp", "co")
_ENUM_FIELDS = {"fee_method", "currency", "billing_frequency", "payment_timing"}


@dataclass(frozen=True)
class Comparison:
    outcome: Outcome
    detail: str | None = None  # for a fee table: names the first differing band, 1-based, e.g. "band 2: amount 400000000 vs 500000000"


def normalise_text(text: str) -> str:
    """Canonicalise entity names and text fields to prevent superficial mismatch."""
    cleaned = text.replace("’", "'").casefold()
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch.isspace())
    cleaned = " ".join(cleaned.split())
    if cleaned == "the":
        cleaned = ""
    elif cleaned.startswith("the "):
        cleaned = cleaned[4:]

    while True:
        dropped = False
        for suffix in _LEGAL_SUFFIXES:
            if cleaned == suffix:
                cleaned = ""
                dropped = True
                break
            if cleaned.endswith(" " + suffix):
                cleaned = cleaned[:-len(suffix) - 1].rstrip()
                dropped = True
                break
        if not dropped:
            break

    return cleaned


def compare_enum(a: str | None, b: str | None) -> Comparison:
    """Compare enumeration codes strictly for string equality."""
    if a is None and b is None:
        return Comparison("agree")
    if a is None or b is None:
        return Comparison("disagree")
    return Comparison("agree" if a == b else "disagree")


def _parse_date(text: str) -> date | None:
    stripped = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(stripped, fmt).date()
        except ValueError:
            continue
    return None


def compare_date(a: str | None, b: str | None) -> Comparison:
    """Verify calendar dates across alternative text formats."""
    if a is None and b is None:
        return Comparison("agree")
    if a is None or b is None:
        return Comparison("disagree")
    da = _parse_date(a) if isinstance(a, str) else None
    if da is None:
        return Comparison("disagree", detail="extracted date does not parse")
    db = _parse_date(b) if isinstance(b, str) else None
    if db is None:
        return Comparison("unreadable")
    return Comparison("agree" if da == db else "disagree")


def compare_int(a: int | None, b: int | None) -> Comparison:
    """Compare integer quantities with exact equality."""
    if a is None and b is None:
        return Comparison("agree")
    if a is None or b is None:
        return Comparison("disagree")
    if a == b:
        return Comparison("agree")
    try:
        if int(a) == int(b):
            return Comparison("agree")
    except (ValueError, TypeError):
        pass
    return Comparison("disagree")


def compare_text(a: str | None, b: str | None) -> Comparison:
    """Compare free text allowing minor OCR/typing variance."""
    if a is None and b is None:
        return Comparison("agree")
    if a is None or b is None:
        return Comparison("disagree")
    norm_a = normalise_text(a if isinstance(a, str) else str(a))
    norm_b = normalise_text(b if isinstance(b, str) else str(b))
    if norm_a == norm_b:
        return Comparison("agree")
    if SequenceMatcher(None, norm_a, norm_b).ratio() >= TEXT_SIMILARITY:
        return Comparison("agree")
    return Comparison("disagree")


def compare_names(a: Sequence[str] | None, b: Sequence[str] | None) -> Comparison:
    """Compare signatory lists as sets of normalised names."""
    if a is None and b is None:
        return Comparison("agree")
    if a is None or b is None:
        return Comparison("disagree")
    seq_a = [a] if isinstance(a, str) else a
    seq_b = [b] if isinstance(b, str) else b
    try:
        set_a = {normalise_text(x) for x in seq_a}
        set_b = {normalise_text(y) for y in seq_b}
        return Comparison("agree" if set_a == set_b else "disagree")
    except (TypeError, AttributeError):
        return Comparison("disagree")


def compare_fee_table(a: Sequence[Mapping] | None, b: Sequence[Mapping] | None) -> Comparison:
    """Verify fee schedule bands by rate and upper bound amount without tolerance."""
    if a is None and b is None:
        return Comparison("agree")
    if a is None or b is None:
        return Comparison("disagree")

    rates_a: list[Decimal] = []
    for band in a:
        rate_val = band.get("rate_text")
        rate_text = "" if rate_val is None else str(rate_val)
        try:
            rates_a.append(parse_rate_bps(rate_text))
        except FeeTextError:
            return Comparison("disagree", detail="extracted table does not parse")

    rates_b: list[Decimal] = []
    for band in b:
        rate_val = band.get("rate_text")
        rate_text = "" if rate_val is None else str(rate_val)
        try:
            rates_b.append(parse_rate_bps(rate_text))
        except FeeTextError:
            return Comparison("unreadable")

    if len(a) != len(b):
        return Comparison("disagree", detail=f"band count {len(a)} vs {len(b)}")

    for i, (band_a, band_b, rate_a, rate_b) in enumerate(zip(a, b, rates_a, rates_b), start=1):
        if rate_a != rate_b:
            ra = format(rate_a.normalize(), "f")
            rb = format(rate_b.normalize(), "f")
            return Comparison("disagree", detail=f"band {i}: rate {ra} vs {rb} bps")
        band_text_a = band_a.get("band_text")
        band_text_b = band_b.get("band_text")
        amount_a = parse_amount_minor(str(band_text_a)) if band_text_a is not None else None
        amount_b = parse_amount_minor(str(band_text_b)) if band_text_b is not None else None
        if amount_a != amount_b:
            return Comparison("disagree", detail=f"band {i}: amount {amount_a} vs {amount_b}")

    return Comparison("agree")


def compare_field(field_path: str, extracted: object, read: object) -> Comparison:
    """Route field verification by schema path to appropriate comparison rule."""
    base_name = re.sub(r"\[\d+\]$", "", field_path)

    if base_name == "fee_tiers":
        return compare_fee_table(cast(Sequence[Mapping] | None, extracted), cast(Sequence[Mapping] | None, read))
    if base_name in _ENUM_FIELDS:
        return compare_enum(cast(str | None, extracted), cast(str | None, read))
    if base_name.endswith("_date"):
        return compare_date(cast(str | None, extracted), cast(str | None, read))
    if base_name == "termination_notice_days":
        return compare_int(cast(int | None, extracted), cast(int | None, read))
    if base_name == "signatories":
        return compare_names(cast(Sequence[str] | None, extracted), cast(Sequence[str] | None, read))
    return compare_text(cast(str | None, extracted), cast(str | None, read))
