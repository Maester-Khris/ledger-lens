import uuid

from app.contracts.fields import ElementRef, evaluate_terms
from app.contracts.schema import (
    CitedCurrency, CitedFeeMethod, CitedFrequency, CitedInt, CitedText, CitedTiming, ContractTerms, FeeBandOut,
)
from app.contracts.types import FieldRouting

TABLE = "| On the first $1,000,000 | 1.00% |\n| On the next $1,500,000 | 0.85% |\n| On assets in excess of $2,500,000 | 0.65% |"
ELEMENTS = {
    "E1": ElementRef(uuid.UUID(int=1), "Made between Maple Ridge Wealth Advisors Inc. and <PERSON_0123456789ab>.", 1, 1),
    "E2": ElementRef(uuid.UUID(int=2), "Fees are calculated on a graduated basis, billed quarterly in arrears, payable in Canadian dollars.", 1, 1),
    "E3": ElementRef(uuid.UUID(int=3), "Either party may terminate upon thirty (30) days' written notice.", 1, 1),
    "E4": ElementRef(uuid.UUID(int=4), TABLE, 2, 2),
}
GRADES = {"1": "EXCELLENT", "2": "GOOD"}


def _text(value, quote, *ids):
    return CitedText(value=value, quote=quote, element_ids=list(ids))


def _terms(**overrides):
    base = dict(
        fund_or_account=_text(None, "", ),
        adviser=_text("Maple Ridge Wealth Advisors Inc.", "between Maple Ridge Wealth Advisors Inc. and", "E1"),
        client=_text("<PERSON_0123456789ab>", "and <PERSON_0123456789ab>", "E1"),
        agreement_date=_text(None, ""), effective_date=_text(None, ""), fee_basis=_text(None, ""),
        fee_method=CitedFeeMethod(value="graduated", quote="calculated on a graduated basis", element_ids=["E2"]),
        currency=CitedCurrency(value="CAD", quote="payable in Canadian dollars", element_ids=["E2"]),
        fee_bands=[
            FeeBandOut(band_text="On the first $1,000,000", rate_text="1.00%", quote="On the first $1,000,000 | 1.00%", element_ids=["E4"]),
            FeeBandOut(band_text="On the next $1,500,000", rate_text="0.85%", quote="On the next $1,500,000 | 0.85%", element_ids=["E4"]),
            FeeBandOut(band_text="On assets in excess of $2,500,000", rate_text="0.65%", quote="On assets in excess of $2,500,000 | 0.65%", element_ids=["E4"]),
        ],
        billing_frequency=CitedFrequency(value="quarterly", quote="billed quarterly in arrears", element_ids=["E2"]),
        payment_timing=CitedTiming(value="arrears", quote="billed quarterly in arrears", element_ids=["E2"]),
        termination_notice_days=CitedInt(value=30, quote="thirty (30) days' written notice", element_ids=["E3"]),
        governing_law=_text(None, ""), signatories=[],
    )
    return ContractTerms(**(base | overrides))


def _by_path(results):
    return {r.field_path: r for r in results}


def test_grounded_valid_fields_are_accepted_and_tiers_are_converted():
    results = _by_path(evaluate_terms(_terms(), ELEMENTS, GRADES))
    for path in ("adviser", "client", "fee_method", "currency", "billing_frequency", "payment_timing", "termination_notice_days"):
        assert results[path].routing is FieldRouting.accepted, (path, results[path])
    tier = results["fee_tiers[1]"]
    assert tier.routing is FieldRouting.accepted
    assert tier.value == {"band_text": "On the next $1,500,000", "rate_text": "0.85%", "up_to_minor": 250_000_000, "rate_bps": "85"}
    assert tier.page_grade == "GOOD" and tier.element_ids == [uuid.UUID(int=4)]


def test_paraphrased_quote_is_not_grounded():
    terms = _terms(termination_notice_days=CitedInt(value=30, quote="a month's notice", element_ids=["E3"]))
    result = _by_path(evaluate_terms(terms, ELEMENTS, GRADES))["termination_notice_days"]
    assert (result.grounded, result.routing) == (False, FieldRouting.needs_review)


def test_unknown_element_id_is_not_grounded():
    terms = _terms(adviser=_text("Maple Ridge Wealth Advisors Inc.", "Maple Ridge Wealth Advisors Inc.", "E99"))
    assert _by_path(evaluate_terms(terms, ELEMENTS, GRADES))["adviser"].routing is FieldRouting.needs_review


def test_low_page_grade_sends_to_review():
    result = _by_path(evaluate_terms(_terms(), ELEMENTS, {"1": "EXCELLENT", "2": "FAIR"}))["fee_tiers[0]"]
    assert (result.grounded, result.page_grade, result.routing) == (True, "FAIR", FieldRouting.needs_review)


def test_bad_schedule_flags_every_tier():
    bands = _terms().fee_bands[:2]  # no open-ended band
    results = evaluate_terms(_terms(fee_bands=bands), ELEMENTS, GRADES)
    tiers = [r for r in results if r.field_path.startswith("fee_tiers")]
    assert tiers and all(r.routing is FieldRouting.needs_review and r.validator_errors for r in tiers)


def test_validators():
    terms = _terms(
        client=_text("Maple Ridge Wealth Advisors Inc.", "between Maple Ridge Wealth Advisors Inc. and", "E1"),
        termination_notice_days=CitedInt(value=400, quote="thirty (30) days' written notice", element_ids=["E3"]),
    )
    results = _by_path(evaluate_terms(terms, ELEMENTS, GRADES))
    assert "adviser and client are the same party" in results["client"].validator_errors
    assert results["termination_notice_days"].validator_errors == ["notice period outside 0–365 days"]


def test_missing_required_field_is_reviewed():
    results = _by_path(evaluate_terms(_terms(fee_bands=[]), ELEMENTS, GRADES))
    assert results["fee_tiers"].validator_errors == ["required field is missing"]
    assert results["fee_tiers"].routing is FieldRouting.needs_review
