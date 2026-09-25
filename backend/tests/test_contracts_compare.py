from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app import config
from app.contracts import dao as contracts_dao
from app.contracts.compare import compare_contract_to_billing, comparison_to_json
from app.contracts.errors import ContractNotComparable
from app.contracts.fields import FieldResult
from app.contracts.types import FieldRouting
from app.documents import dao as documents_dao
from app.documents.sniff import PdfFacts
from tests.support import build_fee_scenario
from tests.test_contracts_dao import CONFIG

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
TIERS = [("On the first $1,000,000", "1.00%", 100_000_000, "100"), ("On the next $1,500,000", "0.85%", 250_000_000, "85"),
         ("On assets in excess of $2,500,000", "0.65%", None, "65")]


def _accepted(path, value):
    return FieldResult(path, value, [], "q", True, [], "GOOD", FieldRouting.accepted)


def _contract(db_session, tenant_id, household_id, *, tier_routing=FieldRouting.accepted, key="tremblay-ima"):
    data = FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key=key, title="Tremblay IMA", source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR, household_id=household_id,
    ).version
    results = [_accepted("fee_method", "graduated"), _accepted("currency", "CAD")]
    for i, (band, rate, up_to, bps) in enumerate(TIERS):
        value = {"band_text": band, "rate_text": rate, "up_to_minor": up_to, "rate_bps": bps}
        results.append(FieldResult(f"fee_tiers[{i}]", value, [], band, tier_routing is FieldRouting.accepted, [], "GOOD", tier_routing))
    contracts_dao.save_run(db_session, version.id, CONFIG, {}, results)
    db_session.commit()
    return version.document_id


def test_leakage_gap_on_the_second_tier(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)  # 1.8M CAD household; billing tier 2 is 0.80%
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    result = compare_contract_to_billing(db_session, tenant_id=tenant_id, document_id=document_id, as_of=date(2026, 9, 30))
    assert result.household_value_minor == 180_000_000
    assert result.contract_annual_fee - result.billing_annual_fee == Decimal("40000")  # 0.05% of the 800,000 in tier 2
    assert result.annual_gap_minor == 40_000
    assert [d.tier_no for d in result.differences] == [2]
    payload = comparison_to_json(result)
    assert payload["annual_gap"] == "400.00" and payload["currency"] == "CAD"
    assert payload["differences"][0]["contract_rate_percent"] == "0.85" and payload["differences"][0]["billing_rate_percent"] == "0.8"


def test_defaults_to_latest_valuation_date(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    assert compare_contract_to_billing(db_session, tenant_id=tenant_id, document_id=document_id).as_of == date(2026, 9, 30)


def test_unvalidated_tiers_are_not_compared(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id, tier_routing=FieldRouting.needs_review)
    with pytest.raises(ContractNotComparable, match="fee_tiers"):
        compare_contract_to_billing(db_session, tenant_id=tenant_id, document_id=document_id)


def test_unlinked_contract_is_not_comparable(db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, key="edgar-fund")
    with pytest.raises(ContractNotComparable, match="household"):
        compare_contract_to_billing(db_session, tenant_id=tenant_id, document_id=document_id)
