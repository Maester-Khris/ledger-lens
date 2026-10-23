import uuid
from datetime import date

from sqlalchemy import select

from app.contracts import dao as contracts_dao
from app.contracts.models import ExtractionRun
from app.contracts.terms import (field_class, field_label, field_reason, field_sort_key, field_status, required_layers,
                                 verification_path)
from app.contracts.types import FieldRouting, ReviewDecision
from tests.support import build_fee_scenario
from tests.test_contracts_compare import _contract

ON = date(2026, 9, 30)


def test_field_status_covers_every_case():
    assert field_status(FieldRouting.accepted, None, {}, "adviser") == "accepted"
    assert field_status(FieldRouting.needs_review, None, {}, "adviser") == "needs_review"
    assert field_status(FieldRouting.needs_review, ReviewDecision.confirmed, {}, "adviser") == "confirmed"
    assert field_status(FieldRouting.needs_review, ReviewDecision.corrected, {}, "adviser") == "corrected"
    assert field_status(FieldRouting.accepted, ReviewDecision.rejected, {}, "adviser") == "rejected"


def test_field_classes_and_required_layers():
    assert [field_class(p) for p in ("fee_tiers[3]", "fee_basis", "client", "effective_date", "governing_law",
                                     "signatories[0]")] == ["A", "A", "B", "B", "C", "C"]
    assert required_layers("fee_tiers[0]") == required_layers("fee_basis") == {"ocr_local", "vision"}
    assert required_layers("currency") == {"vision"}  # inferred: no text to re-read
    assert required_layers("client") == required_layers("agreement_date") == frozenset()
    assert verification_path("fee_tiers[2]") == "fee_tiers" and verification_path("signatories[1]") == "signatories[1]"


def test_class_a_without_verification_is_not_served():
    assert field_status(FieldRouting.accepted, None, {}, "fee_tiers[0]") == "needs_review"
    assert field_status(FieldRouting.accepted, None, {"ocr_local": "agree"}, "fee_tiers[0]") == "needs_review"


def test_class_a_served_when_all_required_layers_agree():
    assert field_status(FieldRouting.accepted, None, {"ocr_local": "agree", "vision": "agree"}, "fee_tiers[1]") == "accepted"
    assert field_status(FieldRouting.accepted, None, {"vision": "agree"}, "fee_method") == "accepted"


def test_error_or_unreadable_never_counts_as_agree():
    for bad in ("error", "unreadable", "disagree"):
        assert field_status(FieldRouting.accepted, None, {"ocr_local": "agree", "vision": bad}, "fee_basis") == "needs_review"
        assert field_status(FieldRouting.accepted, None, {"ocr_local": bad}, "adviser") == "needs_review"


def test_class_b_and_c_served_as_today_unless_a_check_disagrees():
    assert field_status(FieldRouting.accepted, None, {}, "client") == "accepted"
    assert field_status(FieldRouting.accepted, None, {}, "governing_law") == "accepted"
    assert field_status(FieldRouting.accepted, None, {"ocr_local": "disagree"}, "client") == "needs_review"


def test_human_decision_outranks_verifier():
    assert field_status(FieldRouting.accepted, ReviewDecision.confirmed, {"vision": "disagree"}, "currency") == "confirmed"


def test_reason_names_the_verification_problem_after_the_extraction_reasons():
    assert field_reason("needs_review", True, [], "EXCELLENT", None, "verifier disagreed") == "verifier disagreed"
    assert field_reason("needs_review", True, [], "GOOD", None, "awaiting verification") == "awaiting verification"
    assert field_reason("needs_review", False, [], "GOOD", None, "verifier disagreed") == "not grounded in the cited text"
    assert field_reason("needs_review", True, [], "GOOD", None) == "awaiting review"


def test_bands_sort_numerically_and_have_labels():
    # Review Focus 3
    paths = ["fee_tiers[10]", "fee_tiers[2]", "currency"]
    assert sorted(paths, key=field_sort_key) == ["currency", "fee_tiers[2]", "fee_tiers[10]"]
    assert field_label("fee_tiers[0]") == "Fee band 1"


def test_terms_with_household_and_schedule(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    view = contracts_dao.terms_view(db_session, tenant_id, document_id, ON)
    by_path = {f.path: f for f in view.fields}
    assert by_path["currency"].status == "accepted" and by_path["currency"].group == "fee_schedule"
    assert view.household is not None and view.schedule is not None and view.schedule.tiers


def test_needs_review_then_confirmed_and_corrected(db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, tier_routing=FieldRouting.needs_review, key="terms-review")
    view = contracts_dao.terms_view(db_session, tenant_id, document_id, ON)
    tier = next(f for f in view.fields if f.path == "fee_tiers[0]")
    assert tier.status == "needs_review" and tier.reason == "not grounded in the cited text"
    run_id = db_session.scalars(select(ExtractionRun.id).order_by(ExtractionRun.created_at.desc())).first()
    contracts_dao.record_review(db_session, tenant_id=tenant_id, run_id=run_id, field_path="fee_tiers[0]",
                                decision=ReviewDecision.confirmed, corrected_value=None, reason=None, decided_by="t")
    contracts_dao.record_review(db_session, tenant_id=tenant_id, run_id=run_id, field_path="fee_tiers[1]",
                                decision=ReviewDecision.corrected, corrected_value={"rate_text": "0.90%"}, reason="typo", decided_by="t")
    db_session.commit()
    by_path = {f.path: f for f in contracts_dao.terms_view(db_session, tenant_id, document_id, ON).fields}
    assert by_path["fee_tiers[0]"].status == "confirmed" and by_path["fee_tiers[0]"].reason is None
    assert by_path["fee_tiers[1]"].status == "corrected" and by_path["fee_tiers[1]"].value == {"rate_text": "0.90%"}


def test_no_household_means_null_household_and_schedule(db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, key="terms-fund")
    view = contracts_dao.terms_view(db_session, tenant_id, document_id, ON)
    assert view.household is None and view.schedule is None


def test_api_404_and_not_extracted(client, db_session, tenant_id):
    assert client.get(f"/documents/{uuid.uuid4()}/terms").status_code == 404
    document_id = _contract(db_session, tenant_id, None, key="terms-api")
    body = client.get(f"/documents/{document_id}/terms").json()
    assert body["extraction"]["fields"] and body["coming_soon"][0] == "fee_schedule_history"
