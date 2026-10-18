"""X1 labels (spec section 10): a blind, stratified random sample of auto-accepted fields; crops exported redacted;
labels imported from a CSV; LLM judges read the same exported crops, never the extracted value."""
import csv
import io
import json
import uuid
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from app.contracts import dao
from app.contracts.fields import FieldResult
from app.contracts.models import FieldLabel, FieldReview
from app.contracts.types import FieldRouting, ReviewDecision
from app.contracts.verify import VisionVerifier
from app.documents import store
from scripts.x1_crop_vs_page import crop_vs_page
from scripts.x1_judge import judge
from scripts.x1_label_export import draw_sample, export
from scripts.x1_label_import import read_labels
from tests.test_contracts_dao import CONFIG
from tests.test_contracts_vision import FakeVision
from tests.test_retrieval_index import parsed_version

BANDS = [{"band_text": "On the first $1,000,000", "rate_text": "1.00%", "up_to_minor": 100_000_000, "rate_bps": "100"},
         {"band_text": "Thereafter", "rate_text": "0.65%", "up_to_minor": None, "rate_bps": "65"}]


def _accepted(path, value):
    return FieldResult(path, value, [], "q", True, [], "GOOD", FieldRouting.accepted)


def _run(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    results = [_accepted(f"fee_tiers[{i}]", b) for i, b in enumerate(BANDS)] + [
        _accepted("currency", "CAD"), _accepted("fee_method", "graduated"), _accepted("adviser", "Maple Ridge"),
        _accepted("fund_or_account", "Household"), _accepted("governing_law", "Ontario")]
    run = dao.save_run(db_session, version.id, CONFIG, {}, results)
    for path, layers in (("fee_tiers", ("ocr_local", "vision")), ("currency", ("vision",))):
        for layer in layers:
            dao.save_verification(db_session, dao.VerificationRow(run.id, path, layer, "v", "element", None, "agree"))
    db_session.add(FieldReview(run_id=run.id, field_path="fund_or_account", decision=ReviewDecision.confirmed,
                               decided_by="t"))
    db_session.commit()
    return run


def test_auto_accepted_fields_are_the_served_machine_decisions(db_session, tenant_id):
    run = _run(db_session, tenant_id)
    fields = {(p, c) for r, p, c in dao.auto_accepted_fields(db_session) if r == run.id}
    # fee_method is unverified (not served), fund_or_account was decided by a person: neither is a machine decision
    assert fields == {("fee_tiers", "A"), ("currency", "A"), ("adviser", "B"), ("governing_law", "C")}


def test_draw_sample_is_stratified_and_seeded():
    population = [(uuid.UUID(int=i), f"f{i}", "ABC"[i % 3]) for i in range(30)]
    first = draw_sample(population, seed=7, per_class={"A": 4, "B": 2, "C": 1})
    assert [c for _r, _p, c in first].count("A") == 4 and len(first) == 7
    assert first == draw_sample(population, seed=7, per_class={"A": 4, "B": 2, "C": 1})  # reproducible
    assert first != draw_sample(population, seed=8, per_class={"A": 4, "B": 2, "C": 1})
    assert len(draw_sample(population, seed=7, per_class={"A": 50})) == 10  # never more than the class holds


def test_export_writes_redacted_crops_and_a_csv_without_values(db_session, tenant_id, tmp_path):
    run = _run(db_session, tenant_id)
    store_root = tmp_path / "store"
    for path in ("fee_tiers", "currency"):
        target = store.crop_path(store_root, run.id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (30, 10), "white").save(target)
    sample = [(run.id, "fee_tiers", "A"), (run.id, "currency", "A"), (run.id, "adviser", "B")]  # adviser: no crop

    def redact(image: Image.Image) -> Image.Image:
        return Image.new("RGB", image.size, "black")  # a marker: the exported file must be the redacted one

    written = export(sample, out_dir=tmp_path / "out", store_root=store_root, redact=redact)
    assert written == 2
    rows = list(csv.DictReader(open(tmp_path / "out" / "labels.csv")))
    assert [(r["field_path"], r["value"]) for r in rows] == [("fee_tiers", ""), ("currency", "")]
    assert set(rows[0]) == {"item", "run_id", "field_path", "crop_file", "value"}
    text = (tmp_path / "out" / "labels.csv").read_text()
    assert "CAD" not in text and "1.00%" not in text  # the labeller never sees the extracted value
    crop = Image.open(tmp_path / "out" / rows[0]["crop_file"]).convert("RGB")
    assert crop.getpixel((0, 0)) == (0, 0, 0)


def _csv(tmp_path, rows) -> Path:
    path = tmp_path / "labels.csv"
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["item", "run_id", "field_path", "crop_file", "value"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_import_parses_values_and_rejects_bad_input(tmp_path):
    run_id = str(uuid.uuid4())
    path = _csv(tmp_path, [
        {"item": 1, "run_id": run_id, "field_path": "currency", "crop_file": "crops/1.png", "value": "CAD"},
        {"item": 2, "run_id": run_id, "field_path": "fee_tiers", "crop_file": "crops/2.png",
         "value": json.dumps([{"band_text": "Thereafter", "rate_text": "0.65%"}])},
        {"item": 3, "run_id": run_id, "field_path": "termination_notice_days", "crop_file": "crops/3.png", "value": "30"},
        {"item": 4, "run_id": run_id, "field_path": "effective_date", "crop_file": "crops/4.png", "value": "null"},
    ])
    rows = read_labels(path, "human:niki")
    assert [r.label_value for r in rows] == ["CAD", [{"band_text": "Thereafter", "rate_text": "0.65%"}], 30, None]
    assert all(r.blind and r.labeller == "human:niki" for r in rows)
    with pytest.raises(ValueError, match="labeller"):
        read_labels(path, "someone")
    blank = _csv(tmp_path, [{"item": 1, "run_id": run_id, "field_path": "currency", "crop_file": "c.png", "value": " "}])
    with pytest.raises(ValueError, match="item 1"):
        read_labels(blank, "judge:claude")


def test_save_labels_roundtrip(db_session, tenant_id, tmp_path):
    run = _run(db_session, tenant_id)
    path = _csv(tmp_path, [{"item": 1, "run_id": str(run.id), "field_path": "currency", "crop_file": "c.png", "value": "CAD"}])
    dao.save_labels(db_session, read_labels(path, "adjudicated"))
    db_session.commit()
    label = db_session.scalars(select(FieldLabel).where(FieldLabel.run_id == run.id)).one()
    assert (label.labeller, label.label_value, label.blind) == ("adjudicated", "CAD", True)


def test_judge_reads_the_exported_bytes_and_fills_the_csv(tmp_path):
    (tmp_path / "crops").mkdir()
    for n, colour in ((1, "white"), (2, "black")):
        Image.new("RGB", (20, 10), colour).save(tmp_path / "crops" / f"{n}.png")
    run_id = str(uuid.uuid4())
    path = _csv(tmp_path, [
        {"item": 1, "run_id": run_id, "field_path": "currency", "crop_file": "crops/1.png", "value": ""},
        {"item": 2, "run_id": run_id, "field_path": "fee_method", "crop_file": "crops/2.png", "value": ""},
    ])
    model = FakeVision(answers={"currency": {"value": "CAD"}, "fee_method": TimeoutError("judge timed out")})
    out = tmp_path / "judged.csv"
    judge(path, out, VisionVerifier(model, "claude-x"))
    rows = list(csv.DictReader(open(out)))
    assert rows[0]["value"] == "CAD" and rows[0]["error"] == ""
    assert rows[1]["value"] == "" and "timed out" in rows[1]["error"]
    sent = []
    for messages in model.seen:
        part = next(p for p in messages[-1].content if isinstance(p, dict) and p.get("type") == "image_url")
        sent.append(part["image_url"]["url"].split(",", 1)[1])
    import base64
    assert base64.b64decode(sent[0]) == (tmp_path / "crops" / "1.png").read_bytes()  # the very file a human labels


def _png(width: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, 10)).save(buffer, format="PNG")
    return buffer.getvalue()


class BySize(FakeVision):
    """Answers by (field, image width): calls run concurrently, so answers cannot depend on call order."""

    def with_structured_output(self, schema, include_raw=False, **kwargs):
        import base64
        import re

        from langchain_core.messages import AIMessage
        from langchain_core.runnables import RunnableLambda

        def run(messages):
            parts = messages[-1].content
            field = re.search(r"field: (\S+)", next(p["text"] for p in parts if p.get("type") == "text")).group(1)
            data = next(p for p in parts if p.get("type") == "image_url")["image_url"]["url"].split(",", 1)[1]
            width = Image.open(io.BytesIO(base64.b64decode(data))).width
            return {"raw": AIMessage(content=""), "parsed": schema.model_validate(self.answers[f"{field}:{width}"]),
                    "parsing_error": None}

        return RunnableLambda(run)


def test_crop_vs_page_scores_both_against_the_labels():
    items = [{"field_path": "currency", "label": "CAD", "crop_png": _png(10), "page_png": _png(20)},
             {"field_path": "fee_method", "label": "graduated", "crop_png": _png(10), "page_png": _png(20)}]
    model = BySize(answers={"currency:10": {"value": "CAD"}, "currency:20": {"value": "CAD"},
                            "fee_method:10": {"value": "cliff"}, "fee_method:20": {"value": "graduated"}})
    report = crop_vs_page(items, VisionVerifier(model, "gpt-6-luna"))
    assert report["n"] == 2
    assert report["crop"]["correct"] == 1 and report["page"]["correct"] == 2
    assert report["crop"]["accuracy"] == pytest.approx(0.5) and report["page"]["accuracy"] == pytest.approx(1.0)


def test_judge_population_excludes_personal_fields():
    from scripts.x1_label_export import judge_population
    population = [(uuid.UUID(int=1), "client", "B"), (uuid.UUID(int=1), "adviser", "B"), (uuid.UUID(int=1), "governing_law", "C"),
                  (uuid.UUID(int=1), "signatories[0]", "C")]
    assert [p for _r, p, _c in judge_population(population)] == ["adviser", "governing_law"]


@pytest.mark.slow
def test_render_missing_crop_for_an_unchecked_class_c_field(db_session, tenant_id):
    from app import config
    from scripts.x1_label_export import render_missing_crops
    from tests.test_contracts_verify import fixture_run
    _version, run = fixture_run(db_session, tenant_id, "x1-label-crop")
    target = store.crop_path(config.DOCUMENT_STORE_DIR, run.id, "governing_law")
    assert not target.exists()
    assert render_missing_crops(db_session, [(run.id, "governing_law", "C")], store_root=config.DOCUMENT_STORE_DIR) == 1
    assert Image.open(target).width > 0
    assert render_missing_crops(db_session, [(run.id, "governing_law", "C")], store_root=config.DOCUMENT_STORE_DIR) == 0
