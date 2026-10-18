"""X1 per-stage report (spec section 11): cost, time and confidence per stage, labelled error rates with an honest
upper bound, and 100k projections that name their prices and assumptions."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.contracts import dao
from app.contracts.fields import FieldResult
from app.contracts.models import FieldLabel
from app.contracts.types import FieldRouting
from app.documents.models import VersionEvent
from app.documents.types import VersionStage
from scripts.x1_report import (A_TIGHT, TARGETS, build_report, class_verdict, clopper_pearson_upper, cohen_kappa,
                               percentiles, render_markdown)
from tests.test_contracts_dao import CONFIG
from tests.test_retrieval_index import parsed_version


def test_clopper_pearson_upper_bound():
    assert clopper_pearson_upper(0, 60) == pytest.approx(0.0487, abs=0.0005)  # the "about 3/n" rule
    assert clopper_pearson_upper(0, 300) == pytest.approx(0.00994, abs=0.0002)
    assert clopper_pearson_upper(1, 60) == pytest.approx(0.0766, abs=0.0005)  # one-sided 95%, as the spec states
    assert clopper_pearson_upper(60, 60) == 1.0
    with pytest.raises(ValueError):
        clopper_pearson_upper(0, 0)


def test_class_verdict_against_targets():
    assert TARGETS == {"A": 0.05, "B": 0.05, "C": 0.10} and A_TIGHT == 0.01
    assert class_verdict(0, 60, TARGETS["A"]) is True
    assert class_verdict(1, 60, TARGETS["A"]) is False
    assert class_verdict(0, 30, TARGETS["C"]) is True
    assert class_verdict(0, 59, TARGETS["A"]) is True  # 59 is the smallest sample that supports 5%
    assert class_verdict(0, 58, TARGETS["A"]) is False


def test_cohen_kappa():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == pytest.approx(0.0)
    assert cohen_kappa(["a", "a"], ["a", "a"]) == 1.0  # one category, full agreement


def test_percentiles():
    assert percentiles([]) == (None, None)
    assert percentiles([5.0]) == (5.0, 5.0)
    median, p95 = percentiles([float(v) for v in range(1, 101)])
    assert median == pytest.approx(50.5) and p95 == pytest.approx(95.05)


def _event(session, version_id, stage, at, detail):
    session.add(VersionEvent(version_id=version_id, stage=stage, detail=detail, created_at=at))


def test_build_report_on_one_x1_document(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)  # adds stored and parsed events at "now"
    t0 = datetime(2030, 1, 1, tzinfo=timezone.utc)  # later than anything else in the test database
    run = dao.save_run(db_session, version.id, CONFIG, {}, [
        FieldResult("currency", "CAD", [], "q", True, [], "GOOD", FieldRouting.accepted),
        FieldResult("adviser", "X", [], "q", True, [], "GOOD", FieldRouting.accepted),
        FieldResult("fee_method", "cliff", [], "q", False, [], "GOOD", FieldRouting.needs_review)])
    dao.save_verification(db_session, dao.VerificationRow(run.id, "currency", "vision", "gpt-6-luna", "element", "CAD",
                                                          "agree", input_tokens=400, output_tokens=14,
                                                          cost_usd=__import__("decimal").Decimal("0.000047"), latency_ms=2400))
    dao.save_verification(db_session, dao.VerificationRow(run.id, "adviser", "ocr_local", "rapidocr", "element", "X",
                                                          "agree", latency_ms=1500))
    for stage, seconds, detail in (
        (VersionStage.stored, 0, {}), (VersionStage.parsed, 20, {"cpu_seconds": 18.0, "page_grades": {"1": "GOOD"}}),
        (VersionStage.extracted, 32, {"run_id": str(run.id), "input_tokens": 5000, "output_tokens": 600, "cost_usd": 0.0148,
                                      "accepted": 2, "needs_review": 1}),
        (VersionStage.verified, 40, {"run_id": str(run.id), "ocr_ms": 1500, "vision_ms": 2400, "cost_usd": 0.000047}),
        (VersionStage.indexed, 43, {"element_count": 1, "embedding_chars": 4000}),
    ):
        _event(db_session, version.id, stage, t0 + timedelta(seconds=seconds), detail)
    db_session.add(FieldLabel(run_id=run.id, field_path="currency", labeller="adjudicated", label_value="CAD", blind=True))
    db_session.commit()

    report = build_report(db_session, label="t", since=t0, chat_usd_per_answer=0.004)
    assert report["documents"] == 1
    stages = report["stages"]
    assert stages["extract"]["usd_per_doc"]["median"] == pytest.approx(0.0148)
    assert stages["verify"]["usd_per_doc"]["median"] == pytest.approx(0.000047)
    assert stages["parse_redact"]["cpu_seconds"]["median"] == 18.0
    assert stages["index"]["usd_per_doc"]["median"] == pytest.approx(1000 * 0.02 / 1e6)  # 4000 chars / 4 per token
    assert stages["verify"]["confidence"]["agreement"]["A"]["vision"] == {"agree": 1}
    labelled = stages["verify"]["confidence"]["labelled"]["A"]
    assert (labelled["n"], labelled["errors"], labelled["passes"]) == (1, 0, False)  # one label supports nothing
    assert labelled["ground_truth"] == "adjudicated"
    assert report["end_to_end"]["review_ready_seconds"]["median"] == 40.0
    assert report["end_to_end"]["searchable_seconds"]["median"] == 43.0
    docs = report["projection_100k"]["documents"]
    assert docs["usd"] == pytest.approx(100_000 * (0.0148 + 0.000047 + 0.00002), rel=1e-6)
    assert docs["assumptions"] and docs["prices"]
    dau = report["projection_100k"]["daily_active_users"]
    assert dau["usd_per_day"] == pytest.approx(100_000 * dau["turns_per_user_per_day"] * 0.004)
    markdown = render_markdown(report)
    assert "| verify |" in markdown and "list prices" in markdown.lower()
    json.dumps(report)  # serialisable as written to reports/x1-<label>.json


def test_report_counts_only_documents_ingested_through_x1_for_end_to_end_times(db_session, tenant_id):
    # A backfilled document was indexed before it was verified: its stored->verified time is weeks, not a measurement.
    version = parsed_version(db_session, tenant_id)
    t0 = datetime(2031, 1, 1, tzinfo=timezone.utc)
    for stage, seconds in ((VersionStage.stored, 0), (VersionStage.parsed, 20), (VersionStage.indexed, 25),
                           (VersionStage.extracted, 40), (VersionStage.verified, 900_000)):
        _event(db_session, version.id, stage, t0 + timedelta(seconds=seconds), {})
    db_session.commit()
    report = build_report(db_session, label="t", since=t0, chat_usd_per_answer=0.004)
    assert report["end_to_end"]["review_ready_seconds"] == {"n": 0, "median": None, "p95": None}


def test_labelled_error_is_measured_on_the_machine_value_even_after_a_human_fix(db_session, tenant_id):
    # The sample measures what the machine auto-accepted. A person correcting the field later must not erase the error.
    from app.contracts.models import FieldReview
    from app.contracts.types import ReviewDecision

    version = parsed_version(db_session, tenant_id)
    t0 = datetime(2032, 1, 1, tzinfo=timezone.utc)
    run = dao.save_run(db_session, version.id, CONFIG, {}, [
        FieldResult("governing_law", "Quebec", [], "q", True, [], "GOOD", FieldRouting.accepted)])
    _event(db_session, version.id, VersionStage.stored, t0, {})
    db_session.add(FieldLabel(run_id=run.id, field_path="governing_law", labeller="human:niki", label_value="Ontario",
                              blind=True))
    db_session.add(FieldReview(run_id=run.id, field_path="governing_law", decision=ReviewDecision.corrected,
                               corrected_value="Ontario", decided_by="t"))
    db_session.commit()
    labelled = build_report(db_session, label="t", since=t0, chat_usd_per_answer=0.004)["stages"]["verify"]["confidence"]["labelled"]["C"]
    assert (labelled["n"], labelled["errors"]) == (1, 1)


def test_backfilled_documents_report_verify_work_not_wall_time_and_flag_missing_costs(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    t0 = datetime(2033, 1, 1, tzinfo=timezone.utc)
    for stage, seconds, detail in (
        (VersionStage.stored, 0, {}), (VersionStage.parsed, 20, {}), (VersionStage.indexed, 25, {"embedding_chars": 400}),
        (VersionStage.extracted, 40, {"run_id": "x"}),  # predates token logging: no cost
        (VersionStage.verified, 900_000, {"ocr_ms": 5000, "vision_ms": 3000, "cost_usd": 0.0003}),
    ):
        _event(db_session, version.id, stage, t0 + timedelta(seconds=seconds), detail)
    db_session.commit()
    report = build_report(db_session, label="t", since=t0, chat_usd_per_answer=0.004)
    verify = report["stages"]["verify"]
    assert verify["time_seconds"]["n"] == 0  # stored->verified spans weeks on a backfill: not a measurement
    assert verify["work_seconds"]["median"] == 8.0  # OCR + vision time recorded by the stage itself
    documents = report["projection_100k"]["documents"]
    assert documents["usd"] is None and "extract" in documents["missing"]  # never a total that drops a stage
    assert "not measured" in render_markdown(report)
    assert "NO LABELS" in render_markdown(report)


def test_min_sample_and_verdict_wording():
    from scripts.x1_report import min_sample, verdict_label
    assert (min_sample(0.05), min_sample(0.10), min_sample(0.01)) == (59, 29, 299)
    assert verdict_label({"n": 0}) == "NO LABELS"
    assert verdict_label({"n": 57, "errors": 0, "target": 0.05, "passes": False}) == "SAMPLE TOO SMALL (needs 59)"
    assert verdict_label({"n": 60, "errors": 0, "target": 0.05, "passes": True}) == "PASS"
    assert verdict_label({"n": 60, "errors": 2, "target": 0.05, "passes": False}) == "FAIL"
    assert verdict_label({"n": 57, "errors": 3, "target": 0.05, "passes": False}) == "FAIL"  # errors fail regardless of n
