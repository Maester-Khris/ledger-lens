"""X1 review queue (spec section 9): a verifier disagreement is one queue item, shown as a diff; a fee table is
reviewed as one unit; the reviewer's evidence crop is served locally and tenant-scoped."""
import uuid

import pytest
from PIL import Image
from sqlalchemy import select

from app import config
from app.contracts import dao
from app.contracts.compare import compare_contract_to_billing
from app.contracts.errors import ContractNotComparable
from app.contracts.fields import FieldResult
from app.contracts.models import FieldReview, GuestFieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from app.assistant import dao as assistant_dao
from tests.support import build_fee_scenario, make_tenant
from tests.test_contracts_compare import TIERS, _contract
from tests.test_contracts_dao import CONFIG
from tests.test_retrieval_index import parsed_version

BANDS = [{"band_text": b, "rate_text": r, "up_to_minor": u, "rate_bps": bps} for b, r, u, bps in TIERS]
READ = [{"band_text": b["band_text"], "rate_text": b["rate_text"]} for b in BANDS]
READ[1] = {"band_text": "On the next $1,500,000", "rate_text": "0.80%"}


def _accepted(path, value):
    return FieldResult(path, value, [], "q", True, [], "GOOD", FieldRouting.accepted)


def _flagged_run(db_session, tenant_id):
    """A run whose fee table the vision verifier read differently (band 2: 0.80% vs 0.85%)."""
    version = parsed_version(db_session, tenant_id)
    results = [_accepted(f"fee_tiers[{i}]", band) for i, band in enumerate(BANDS)]
    results += [_accepted("currency", "CAD"), FieldResult("adviser", "X", [], "q", False, [], "GOOD", FieldRouting.needs_review)]
    run = dao.save_run(db_session, version.id, CONFIG, {"raw": True}, results)
    for row in (
        dao.VerificationRow(run.id, "fee_tiers", "ocr_local", "rapidocr", "table", READ[:1] + BANDS[1:], "agree"),
        dao.VerificationRow(run.id, "fee_tiers", "vision", "gpt-6-luna", "table", READ, "disagree",
                            "band 2: rate 85 vs 80 bps"),
        dao.VerificationRow(run.id, "currency", "vision", "gpt-6-luna", "element", "CAD", "agree"),
    ):
        dao.save_verification(db_session, row)
    db_session.commit()
    return version, run


def _decide(client, run, field_path, decision, **extra):
    return client.post("/reviews", json={"run_id": str(run.id), "field_path": field_path, "decision": decision, **extra})


def _band_reviews(db_session, run):
    return db_session.scalars(select(FieldReview).where(FieldReview.run_id == run.id).order_by(FieldReview.field_path)).all()


def test_disagreement_appears_as_one_table_item(client, db_session, tenant_id):
    _, run = _flagged_run(db_session, tenant_id)
    items = [i for i in client.get("/reviews").json() if i["run_id"] == str(run.id)]
    assert [i["field_path"] for i in items] == ["fee_tiers", "adviser"]  # class A first, then B
    table = items[0]
    assert table["field_class"] == "A" and table["value"] == BANDS
    assert table["verification"]["layer"] == "vision" and table["verification"]["outcome"] == "disagree"
    assert table["verification"]["read_value"] == READ
    assert table["verification"]["detail"] == "band 2: rate 85 vs 80 bps"
    assert items[1]["field_class"] == "B" and items[1]["verification"] is None  # routed by extraction, not a verifier


def test_table_confirm_writes_every_band(client, db_session, tenant_id):
    version, run = _flagged_run(db_session, tenant_id)
    response = _decide(client, run, "fee_tiers", "confirmed")
    assert response.status_code == 201 and response.json()["field_path"] == "fee_tiers"
    assert [(r.field_path, r.decision.value) for r in _band_reviews(db_session, run)] == [
        (f"fee_tiers[{i}]", "confirmed") for i in range(3)]
    assert "fee_tiers" not in [i["field_path"] for i in client.get("/reviews").json() if i["run_id"] == str(run.id)]
    assert {"fee_tiers[0]", "fee_tiers[1]", "fee_tiers[2]"} <= set(
        dao.served_fields(db_session, tenant_id, version.document_id).fields)


def test_table_correction_takes_the_verifiers_bands(client, db_session, tenant_id):
    version, run = _flagged_run(db_session, tenant_id)
    assert _decide(client, run, "fee_tiers", "corrected", corrected_value=READ).status_code == 201
    reviews = _band_reviews(db_session, run)
    assert [r.corrected_value["rate_text"] for r in reviews] == ["1.00%", "0.80%", "0.65%"]
    served = dao.served_fields(db_session, tenant_id, version.document_id)
    # billing's parsers recompute the numbers compare reads; a taken value never carries model arithmetic
    assert served.fields["fee_tiers[1]"].value == {"band_text": "On the next $1,500,000", "rate_text": "0.80%",
                                                   "up_to_minor": 250_000_000, "rate_bps": "80"}


def test_table_correction_that_does_not_parse_is_refused(client, db_session, tenant_id):
    _, run = _flagged_run(db_session, tenant_id)
    broken = [dict(band) for band in READ]
    broken[2] = {"band_text": "On the next $9", "rate_text": "0.65%"}  # the last band must be open-ended
    response = _decide(client, run, "fee_tiers", "corrected", corrected_value=broken)
    assert response.status_code == 422 and response.json()["type"] == "/problems/review-invalid"
    assert _band_reviews(db_session, run) == []


def test_table_correction_band_count_mismatch_writes_nothing(client, db_session, tenant_id):
    _, run = _flagged_run(db_session, tenant_id)
    response = _decide(client, run, "fee_tiers", "corrected", corrected_value=READ[:2])
    assert response.status_code == 422 and response.json()["type"] == "/problems/review-invalid"
    assert _band_reviews(db_session, run) == []


def test_guest_table_review_stays_in_the_overlay(db_session, tenant_id):
    _, run = _flagged_run(db_session, tenant_id)
    guest = assistant_dao.register_guest(db_session, tenant_id, None)
    dao.record_review(db_session, tenant_id=tenant_id, run_id=run.id, field_path="fee_tiers",
                      decision=ReviewDecision.rejected,
                      corrected_value=None, reason=None, decided_by="demo_user", overlay_guest=guest)
    overlay = db_session.scalars(select(GuestFieldReview).where(GuestFieldReview.run_id == run.id)).all()
    assert sorted(r.field_path for r in overlay) == ["fee_tiers[0]", "fee_tiers[1]", "fee_tiers[2]"]
    assert _band_reviews(db_session, run) == []


def test_crop_endpoint_serves_the_png_and_is_tenant_scoped(client, db_session, tenant_id):
    _, run = _flagged_run(db_session, tenant_id)
    crop_dir = config.DOCUMENT_STORE_DIR / "crops" / str(run.id)
    crop_dir.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), "white").save(crop_dir / "fee_tiers.png")
    response = client.get(f"/reviews/{run.id}/crops/fee_tiers")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    items = [i for i in client.get("/reviews").json() if i["run_id"] == str(run.id)]
    assert items[0]["verification"]["crop_url"] == f"/reviews/{run.id}/crops/fee_tiers"
    assert client.get(f"/reviews/{run.id}/crops/currency").status_code == 404  # no file
    assert client.get(f"/reviews/{run.id}/crops/..%2F..%2Fsecret").status_code == 404  # never leaves the crop folder

    other = make_tenant(db_session)
    _, foreign = _flagged_run(db_session, other)
    (config.DOCUMENT_STORE_DIR / "crops" / str(foreign.id)).mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (4, 4)).save(config.DOCUMENT_STORE_DIR / "crops" / str(foreign.id) / "fee_tiers.png")
    assert client.get(f"/reviews/{foreign.id}/crops/fee_tiers").status_code == 404
    assert client.get(f"/reviews/{uuid.uuid4()}/crops/fee_tiers").status_code == 404


def test_compare_reports_unverified_class_a_as_not_comparable(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id, key="x1-unverified", verified=False)
    with pytest.raises(ContractNotComparable) as caught:
        compare_contract_to_billing(db_session, tenant_id=tenant_id, document_id=document_id)
    assert {"fee_method", "currency"} <= set(caught.value.extensions["fields"])


def test_a_partly_reviewed_table_keeps_its_open_bands_in_the_queue(db_session, tenant_id):
    # A table decided band by band before X1: the bands still open stay visible, one item each.
    version = parsed_version(db_session, tenant_id)
    results = [FieldResult(f"fee_tiers[{i}]", band, [], "q", False, [], "GOOD", FieldRouting.needs_review)
               for i, band in enumerate(BANDS)]
    run = dao.save_run(db_session, version.id, CONFIG, {"raw": True}, results)
    db_session.commit()
    dao.record_review(db_session, tenant_id=tenant_id, run_id=run.id, field_path="fee_tiers[0]",
                      decision=ReviewDecision.confirmed, corrected_value=None, reason=None, decided_by="t")
    paths = [p.field_path for p in dao.pending_reviews(db_session, tenant_id) if p.run_id == run.id]
    assert paths == ["fee_tiers[1]", "fee_tiers[2]"]
