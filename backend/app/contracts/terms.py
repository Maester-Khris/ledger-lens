"""What a reviewer sees for each extracted field: its status, why it isn't confirmed, and where it belongs."""
import re
from collections.abc import Mapping
from typing import Literal

from app.contracts.agree import Outcome
from app.contracts.types import FieldRouting, ReviewDecision

FieldStatus = Literal["accepted", "confirmed", "corrected", "rejected", "needs_review"]
SERVED_STATUSES: frozenset[str] = frozenset({"accepted", "confirmed", "corrected"})
COMING_SOON = ("fee_schedule_history", "client_type", "exceptions", "referral_arrangements", "expense_allocation")

_GROUPS = {
    "fund_or_account": "parties", "adviser": "parties", "client": "parties", "signatories": "parties",
    "fee_basis": "fee_schedule", "fee_method": "fee_schedule", "currency": "fee_schedule", "fee_tiers": "fee_schedule",
    "billing_frequency": "billing_terms", "payment_timing": "billing_terms",
    "agreement_date": "term_and_law", "effective_date": "term_and_law",
    "termination_notice_days": "term_and_law", "governing_law": "term_and_law",
}
_LABELS = {
    "fund_or_account": "Fund or account", "adviser": "Adviser", "client": "Client", "signatories": "Signatory",
    "fee_basis": "Fee basis", "fee_method": "Fee method", "currency": "Currency", "fee_tiers": "Fee band",
    "billing_frequency": "Billing frequency", "payment_timing": "Payment timing",
    "agreement_date": "Agreement date", "effective_date": "Effective date",
    "termination_notice_days": "Termination notice (days)", "governing_law": "Governing law",
}
FieldClass = Literal["A", "B", "C"]
# X1 field classes (owner decision 2026-10-17): A moves money, B identifies the parties, C is informational.
_CLASSES: dict[str, FieldClass] = {
    "fee_tiers": "A", "fee_method": "A", "fee_basis": "A", "currency": "A", "billing_frequency": "A", "payment_timing": "A",
    "fund_or_account": "B", "adviser": "B", "client": "B", "effective_date": "B",
}
# The extractor infers these from wording, so there is no text for a local re-read: the vision reading alone checks them.
INFERRED = frozenset({"fee_method", "payment_timing", "billing_frequency", "currency"})
LAYERS = ("ocr_local", "vision")
_PROBLEM_REASONS = {"disagree": "verifier disagreed", "unreadable": "verifier could not read it", "error": "verification failed"}
_INDEXED = re.compile(r"^(?P<base>[a-z_]+)(?:\[(?P<index>\d+)\])?$")


def field_class(path: str) -> FieldClass:
    return _CLASSES.get(_split(path)[0], "C")


def verification_path(path: str) -> str:
    """A fee table is verified, reviewed and labelled as one unit: every band follows the 'fee_tiers' outcome."""
    base = _split(path)[0]
    return base if base == "fee_tiers" else path


def required_layers(path: str) -> frozenset[str]:
    """Checks a field must pass before it is served. Only class A has any: B and C are served as today unless a
    check that did run disagrees."""
    base = _split(path)[0]
    if field_class(base) != "A":
        return frozenset()
    return frozenset({"vision"}) if base in INFERRED else frozenset(LAYERS)


def verification_problem(outcomes: Mapping[str, Outcome], path: str) -> str | None:
    """Why verification holds this field back, or None. A failed or unreadable check never counts as agree."""
    for layer in LAYERS:
        if (outcome := outcomes.get(layer)) is not None and outcome != "agree":
            return _PROBLEM_REASONS[outcome]
    if required_layers(path) - outcomes.keys():
        return "awaiting verification"
    return None


def field_status(routing: FieldRouting, decision: ReviewDecision | None, outcomes: Mapping[str, Outcome],
                 path: str) -> FieldStatus:
    """The one definition of a field's status; served_fields serves exactly SERVED_STATUSES. A person's decision
    outranks every verifier; `outcomes` maps layer -> outcome for this field's verification_path."""
    if decision is ReviewDecision.corrected:
        return "corrected"
    if decision is ReviewDecision.confirmed:
        return "confirmed"
    if decision is ReviewDecision.rejected:
        return "rejected"
    if routing is not FieldRouting.accepted or verification_problem(outcomes, path) is not None:
        return "needs_review"
    return "accepted"


def field_reason(status: FieldStatus, grounded: bool, validator_errors: list[str], page_grade: str,
                 review_reason: str | None, verification: str | None = None) -> str | None:
    """`verification` is verification_problem(...) for the field. The extraction's own reasons come first: they
    explain the routing; a verifier's reason only matters once the extraction itself passed."""
    if status == "rejected":
        return review_reason or "rejected by a reviewer"
    if status != "needs_review":
        return None
    if not grounded:
        return "not grounded in the cited text"
    if validator_errors:
        return validator_errors[0]
    if page_grade not in ("GOOD", "EXCELLENT"):
        return f"low page quality ({page_grade})"
    return verification or "awaiting review"


def _split(path: str) -> tuple[str, int | None]:
    match = _INDEXED.match(path)
    if match is None:
        return path, None
    index = match.group("index")
    return match.group("base"), None if index is None else int(index)


def field_group(path: str) -> str:
    return _GROUPS.get(_split(path)[0], "other")


def field_label(path: str) -> str:
    base, index = _split(path)
    label = _LABELS.get(base, base.replace("_", " ").capitalize())
    return label if index is None else f"{label} {index + 1}"


def field_sort_key(path: str) -> tuple[str, int]:
    base, index = _split(path)
    return base, -1 if index is None else index
