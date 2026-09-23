import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.billing.fee_math import validate_tiers
from app.contracts.fee_text import FeeBand, FeeTextError, tiers_from_bands
from app.contracts.schema import ContractTerms
from app.contracts.types import FieldRouting

GRADE_ORDER = {"POOR": 0, "FAIR": 1, "GOOD": 2, "EXCELLENT": 3}
MIN_ACCEPTED_GRADE = "GOOD"
MAX_ANNUAL_RATE_BPS = 300
MAX_NOTICE_DAYS = 365
DATE_FORMATS = ("%B %d, %Y", "%Y-%m-%d", "%d %B %Y", "%B %d %Y")
REQUIRED = ("adviser", "client", "fee_method", "currency")
# Enum values are chosen, not copied, so grounding looks for wording that supports the choice.
ENUM_EVIDENCE = {
    "graduated": ("graduated", "next", "in excess of", "thereafter"), "cliff": ("entire", "whole", "all assets"),
    "USD": ("$", "dollar", "usd"), "CAD": ("canadian", "cad"),
    "monthly": ("month",), "quarterly": ("quarter",), "annually": ("annual", "year"),
    "arrears": ("arrears",), "advance": ("advance",),
}


@dataclass(frozen=True)
class ElementRef:
    id: uuid.UUID
    text: str
    page_start: int
    page_end: int


@dataclass(frozen=True)
class FieldResult:
    field_path: str
    value: object
    element_ids: list[uuid.UUID]
    quote: str
    grounded: bool
    validator_errors: list[str]
    page_grade: str
    routing: FieldRouting


def _normal(text: str) -> str:
    return " ".join(text.replace("’", "'").split()).casefold()


def _grounded(quote: str, evidence: Iterable[str], cited: Sequence[ElementRef | None], any_of: bool = False) -> bool:
    if not quote.strip() or not cited or any(ref is None for ref in cited):
        return False
    q = _normal(quote)
    if q not in _normal(" ".join(ref.text for ref in cited)):
        return False
    needles = [_normal(e) for e in evidence if e]
    return any(n in q for n in needles) if any_of else all(n in q for n in needles)


def _lowest_grade(cited: Sequence[ElementRef | None], page_grades: Mapping[str, str]) -> str:
    pages = [p for ref in cited if ref for p in range(ref.page_start, ref.page_end + 1)]
    grades = [page_grades.get(str(p), "POOR") for p in pages] or ["POOR"]
    return min(grades, key=lambda g: GRADE_ORDER.get(g, 0))


def _result(path: str, value: object, quote: str, ids: Sequence[str], elements: Mapping[str, ElementRef],
            page_grades: Mapping[str, str], grounded: bool, errors: list[str]) -> FieldResult:
    cited = [elements.get(i) for i in ids]
    grade = _lowest_grade(cited, page_grades)
    accepted = grounded and not errors and GRADE_ORDER.get(grade, 0) >= GRADE_ORDER[MIN_ACCEPTED_GRADE]
    return FieldResult(path, value, [ref.id for ref in cited if ref], quote, grounded, errors, grade,
                       FieldRouting.accepted if accepted else FieldRouting.needs_review)


def _parses_as_date(text: str) -> bool:
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(text.strip(), fmt)
            return True
        except ValueError:
            continue
    return False


def evaluate_terms(terms: ContractTerms, elements: Mapping[str, ElementRef], page_grades: Mapping[str, str]) -> list[FieldResult]:
    results: list[FieldResult] = []

    def cited_field(path: str, item, *, enum: bool = False, errors: list[str] | None = None) -> None:
        errors = list(errors or [])
        if item.value is None and path in REQUIRED:
            errors.append("required field is missing")
        evidence = ENUM_EVIDENCE.get(str(item.value), ()) if enum else [str(item.value)] if item.value is not None else []
        cited = [elements.get(i) for i in item.element_ids]
        grounded = item.value is not None and _grounded(item.quote, evidence, cited, any_of=enum)
        results.append(_result(path, item.value, item.quote, item.element_ids, elements, page_grades, grounded, errors))

    for path in ("fund_or_account", "adviser", "governing_law", "fee_basis"):
        cited_field(path, getattr(terms, path))
    same_party = (terms.client.value is not None and terms.adviser.value is not None
                  and _normal(terms.client.value) == _normal(terms.adviser.value))
    cited_field("client", terms.client, errors=["adviser and client are the same party"] if same_party else [])
    for path in ("agreement_date", "effective_date"):
        item = getattr(terms, path)
        cited_field(path, item, errors=[] if item.value is None or _parses_as_date(item.value) else ["not a date"])
    for path in ("fee_method", "currency", "billing_frequency", "payment_timing"):
        cited_field(path, getattr(terms, path), enum=True)
    notice = terms.termination_notice_days
    out_of_range = notice.value is not None and not 0 <= notice.value <= MAX_NOTICE_DAYS
    cited_field("termination_notice_days", notice, errors=[f"notice period outside 0–{MAX_NOTICE_DAYS} days"] if out_of_range else [])
    for index, signatory in enumerate(terms.signatories):
        cited_field(f"signatories[{index}]", signatory)

    if not terms.fee_bands:
        results.append(_result("fee_tiers", None, "", [], elements, page_grades, False, ["required field is missing"]))
        return results
    schedule_errors: list[str] = []
    tiers = ()
    try:
        tiers = tiers_from_bands([FeeBand(b.band_text, b.rate_text) for b in terms.fee_bands])
        validate_tiers(tiers)
    except (FeeTextError, ValueError) as exc:  # FeeTextError is a ValueError; validate_tiers raises ValueError
        schedule_errors.append(str(exc))
    for index, band in enumerate(terms.fee_bands):
        tier = tiers[index] if tiers else None
        errors = list(schedule_errors)
        if tier is not None and not 0 < tier.rate_bps <= MAX_ANNUAL_RATE_BPS:
            errors.append(f"rate {tier.rate_bps} bps outside (0, {MAX_ANNUAL_RATE_BPS}]")
        value = {"band_text": band.band_text, "rate_text": band.rate_text,
                 "up_to_minor": None if tier is None else tier.up_to_minor,
                 "rate_bps": None if tier is None else format(tier.rate_bps.normalize(), "f")}
        grounded = _grounded(band.quote, [band.band_text, band.rate_text], [elements.get(i) for i in band.element_ids])
        results.append(_result(f"fee_tiers[{index}]", value, band.quote, band.element_ids, elements, page_grades, grounded, errors))
    return results
