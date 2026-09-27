"""What a reviewer sees for each extracted field: its status, why it isn't confirmed, and where it belongs."""
import re
from typing import Literal

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
_INDEXED = re.compile(r"^(?P<base>[a-z_]+)(?:\[(?P<index>\d+)\])?$")


def field_status(routing: FieldRouting, decision: ReviewDecision | None) -> FieldStatus:
    """The one definition of a field's status; served_fields serves exactly SERVED_STATUSES."""
    if decision is ReviewDecision.corrected:
        return "corrected"
    if decision is ReviewDecision.confirmed:
        return "confirmed"
    if decision is ReviewDecision.rejected:
        return "rejected"
    return "accepted" if routing is FieldRouting.accepted else "needs_review"


def field_reason(status: FieldStatus, grounded: bool, validator_errors: list[str], page_grade: str,
                 review_reason: str | None) -> str | None:
    if status == "rejected":
        return review_reason or "rejected by a reviewer"
    if status != "needs_review":
        return None
    if not grounded:
        return "not grounded in the cited text"
    if validator_errors:
        return validator_errors[0]
    if page_grade != "GOOD":
        return f"low page quality ({page_grade})"
    return "awaiting review"


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
