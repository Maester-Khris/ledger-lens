import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import zip_longest

from sqlalchemy.orm import Session

from app.billing import dao as billing_dao
from app.billing.fee_math import Tier, annual_fee, round_half_even
from app.billing.types import FeeMethod
from app.contracts import dao
from app.contracts.errors import ContractNotComparable
from app.documents import dao as documents_dao

MINOR_PER_UNIT = Decimal(100)
BPS_PER_PERCENT = Decimal(100)


@dataclass(frozen=True)
class TierDifference:
    tier_no: int
    contract: Tier | None
    billing: Tier | None


@dataclass(frozen=True)
class Comparison:
    document_id: uuid.UUID
    household_id: uuid.UUID
    as_of: date
    currency: str
    household_value_minor: int
    contract_method: FeeMethod
    billing_method: FeeMethod
    contract_tiers: tuple[Tier, ...]
    billing_tiers: tuple[Tier, ...]
    contract_annual_fee: Decimal
    billing_annual_fee: Decimal
    annual_gap_minor: int  # positive: the firm bills less than the contract allows (leakage)
    differences: list[TierDifference]
    cited_element_ids: list[uuid.UUID]
    revenue_account_id: uuid.UUID
    first_account_id: uuid.UUID


def _contract_terms(served: dao.ServedTerms) -> tuple[FeeMethod, str, tuple[Tier, ...], list[uuid.UUID]]:
    tier_paths = sorted((p for p in served.fields if p.startswith("fee_tiers[")), key=lambda p: int(p[10:-1]))
    missing = [p for p in ("fee_method", "currency") if p not in served.fields]
    missing += [p for p in served.unserved if p.startswith("fee_tiers")]
    if missing or not tier_paths:
        raise ContractNotComparable(f"These fields aren't validated yet: {', '.join(missing) or 'fee_tiers'}.", fields=missing)
    tiers = tuple(Tier(served.fields[p].value["up_to_minor"], Decimal(served.fields[p].value["rate_bps"])) for p in tier_paths)
    cited = sorted({i for p in tier_paths for i in served.fields[p].element_ids})
    return FeeMethod(served.fields["fee_method"].value), served.fields["currency"].value, tiers, cited


def compare_contract_to_billing(session: Session, *, tenant_id: uuid.UUID, document_id: uuid.UUID, as_of: date | None = None) -> Comparison:
    document = documents_dao.find_document(session, tenant_id, document_id)
    if document is None:
        raise ContractNotComparable(f"Document {document_id} does not exist.")
    if document.household_id is None:
        raise ContractNotComparable("This contract is not linked to a billing household (fund-level agreement).")
    served = dao.served_fields(session, tenant_id, document_id)
    if served is None:
        raise ContractNotComparable("This contract hasn't been extracted yet.")
    method, currency, contract_tiers, cited = _contract_terms(served)

    as_of = as_of or billing_dao.latest_valuation_date(session, document.household_id)
    if as_of is None:
        raise ContractNotComparable("The linked household has no account valuations.")
    schedule, version, billing_tiers = billing_dao.schedule_in_effect(session, document.household_id, as_of)
    billing_currency = billing_dao.revenue_currency(session, schedule.id)
    if billing_currency != currency:
        raise ContractNotComparable(f"The contract is in {currency} but billing is in {billing_currency}.")
    accounts = billing_dao.household_accounts(session, document.household_id, as_of)
    value = sum(a.value_minor for a in accounts)

    contract_fee = annual_fee(value, contract_tiers, method)
    billing_fee = annual_fee(value, billing_tiers, version.method)
    differences = [
        TierDifference(n, c, b) for n, (c, b) in enumerate(zip_longest(contract_tiers, billing_tiers), start=1) if c != b
    ]
    return Comparison(document_id, document.household_id, as_of, currency, value, method, version.method,
                      contract_tiers, billing_tiers, contract_fee, billing_fee,
                      round_half_even(contract_fee - billing_fee), differences, cited,
                      schedule.revenue_account_id, accounts[0].account_id)


def _money(minor: Decimal | int) -> str:
    return format((Decimal(minor) / MINOR_PER_UNIT).quantize(Decimal("0.01")), "f")


def _percent(tier: Tier | None) -> str | None:
    return None if tier is None else format((tier.rate_bps / BPS_PER_PERCENT).normalize(), "f")


def comparison_to_json(c: Comparison) -> dict:
    """Every figure the answer may quote, pre-formatted, so the model never formats or computes numbers."""
    return {
        "as_of": c.as_of.isoformat(), "currency": c.currency,
        "household_value": _money(c.household_value_minor),
        "contract_annual_fee": _money(c.contract_annual_fee), "billing_annual_fee": _money(c.billing_annual_fee),
        "annual_gap": _money(c.annual_gap_minor), "annual_gap_minor": c.annual_gap_minor,
        "contract_method": c.contract_method.value, "billing_method": c.billing_method.value,
        "differences": [
            {"tier_no": d.tier_no,
             "contract_up_to": None if d.contract is None or d.contract.up_to_minor is None else _money(d.contract.up_to_minor),
             "contract_rate_percent": _percent(d.contract),
             "billing_up_to": None if d.billing is None or d.billing.up_to_minor is None else _money(d.billing.up_to_minor),
             "billing_rate_percent": _percent(d.billing)}
            for d in c.differences
        ],
    }
