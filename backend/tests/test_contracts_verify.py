"""X1 verify stage (spec sections 6 and 7): layer 1 re-reads each field's cited crop with local OCR."""
import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import select

from app import config
from app.contracts import dao as contracts_dao
from app.contracts.agree import compare_field
from app.contracts.fields import FieldResult
from app.contracts.models import FieldVerification
from app.contracts.types import FieldRouting
from app.contracts.verify import read_local, run_verification
from app.documents import dao as documents_dao
from app.documents.ingest import parse_and_redact
from app.documents.parse import parse_pdf
from app.documents.redact import PiiDetector
from app.documents.sniff import PdfFacts
from app.documents.types import ElementKind, VersionStage
from app.ingestion_pipeline import PIPELINE, next_stage
from tests.test_contracts_dao import CONFIG

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
TABLE = [
    {"band_text": "On the first $1,000,000", "rate_text": "1.00%", "up_to_minor": 100_000_000, "rate_bps": "100"},
    {"band_text": "On the next $1,500,000", "rate_text": "0.85%", "up_to_minor": 250_000_000, "rate_bps": "85"},
    {"band_text": "On assets in excess of $2,500,000", "rate_text": "0.65%", "up_to_minor": None, "rate_bps": "65"},
]


def test_read_local_rereads_fee_table_from_ocr_text():
    ocr = "Household market value Annual rate\nOn the first $1,000,000 1.00%\nOn the next $1,500,000 0.85%\n" \
          "On assets in excess of $2,500,000 0.65%"
    read = read_local("fee_tiers", ocr, TABLE)
    assert [b["rate_text"] for b in read] == ["1.00%", "0.85%", "0.65%"]  # the header has no rate: not a band
    assert compare_field("fee_tiers", TABLE, read).outcome == "agree"


def test_read_local_fee_table_is_an_independent_reading():
    ocr = "On the first $1,000,000 1.00%\nOn the next $1,500,000 0.80%\nOn assets in excess of $2,500,000 0.65%"
    assert compare_field("fee_tiers", TABLE, read_local("fee_tiers", ocr, TABLE)).outcome == "disagree"


def test_read_local_finds_text_and_dates_by_presence():
    ocr = "between Maple Ridge Wealth Advisors Inc. (the \"Adviser\") and effective as of January 1, 2026,"
    assert read_local("adviser", ocr, "Maple Ridge Wealth Advisors Inc.") == "Maple Ridge Wealth Advisors Inc."
    assert read_local("effective_date", ocr, "January 1, 2026") == "January 1, 2026"
    assert read_local("adviser", ocr, "Birch Hill Capital") is None
    assert read_local("fee_tiers", "no rates here", TABLE) is None


@dataclass
class _Event:
    stage: VersionStage
    detail: dict


def test_pipeline_order_is_parse_extract_verify_index():
    assert [s.name for s in PIPELINE] == ["parse_redact", "extract", "verify", "index"]
    reached = [_Event(VersionStage.stored, {}), _Event(VersionStage.parsed, {}), _Event(VersionStage.extracted, {})]
    assert next_stage(PIPELINE, reached).name == "verify"  # index waits until the values are verified
    assert next_stage(PIPELINE, reached + [_Event(VersionStage.verified, {})]).name == "index"


@pytest.mark.slow
def test_verify_stage_end_to_end_on_fixture(db_session, tenant_id):
    data = FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="x1-verify", title="Tremblay IMA", source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version
    keys = {"hmac_key": config.PII_HMAC_KEY, "vault_key": config.PII_VAULT_KEY}
    parse_and_redact(db_session, version.id, parser=parse_pdf, detector=PiiDetector(),
                     store_root=config.DOCUMENT_STORE_DIR, **keys)
    elements = documents_dao.list_elements(db_session, version.id)
    table = next(e for e in elements if e.kind is ElementKind.table)
    parties = next(e for e in elements if "is effective as of" in e.text_redacted)
    fees = next(e for e in elements if "combined household market value" in e.text_redacted)
    client_token = re.search(r"and (.+?) \(together", parties.text_redacted).group(1)
    assert "Tremblay" not in client_token  # stored tokenised; the stage reveals it locally to compare

    def field(path, value, element):
        return FieldResult(path, value, [element.id], "q", True, [], "GOOD", FieldRouting.accepted)

    results = [field(f"fee_tiers[{i}]", band, table) for i, band in enumerate(TABLE)] + [
        field("adviser", "Maple Ridge Wealth Advisors Inc.", parties),
        field("effective_date", "January 1, 2026", parties),
        field("client", client_token, parties),
        field("fee_basis", "combined household market value", fees),
        field("governing_law", "Province of Ontario", parties),  # class C: no live check
    ]
    run = contracts_dao.save_run(db_session, version.id, CONFIG, {}, results)
    documents_dao.append_event(db_session, version.id, VersionStage.extracted, {"run_id": str(run.id)})
    db_session.commit()

    run_verification(db_session, version.id, store_root=config.DOCUMENT_STORE_DIR, vision=None, **keys)

    rows = {r.field_path: r for r in db_session.scalars(select(FieldVerification).where(FieldVerification.run_id == run.id))}
    assert set(rows) == {"fee_tiers", "adviser", "effective_date", "client", "fee_basis"}
    assert {path: (r.layer, r.outcome) for path, r in rows.items()} == {
        path: ("ocr_local", "agree") for path in rows}
    assert rows["fee_tiers"].crop_kind == "table" and rows["adviser"].crop_kind == "element"
    assert "Tremblay" not in str(rows["client"].read_value)  # personal data is stored tokenised
    assert (config.DOCUMENT_STORE_DIR / "crops" / str(run.id) / "fee_tiers.png").exists()
    events = documents_dao.version_events(db_session, version.id)
    assert events[-1].stage is VersionStage.verified and events[-1].detail["run_id"] == str(run.id)
    assert events[-1].detail["outcomes"] == {"agree": 5}

    served = contracts_dao.served_fields(db_session, tenant_id, version.document_id)
    assert "adviser" in served.fields and "fee_tiers[0]" in served.unserved  # class A still needs the vision reading

    run_verification(db_session, version.id, store_root=config.DOCUMENT_STORE_DIR, vision=None, **keys)
    again = db_session.scalars(select(FieldVerification).where(FieldVerification.run_id == run.id)).all()
    assert len(again) == len(rows)  # idempotent re-run
