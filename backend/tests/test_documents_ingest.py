from pathlib import Path

import pytest

from app import config
from app.documents import dao
from app.documents.ingest import parse_and_redact
from app.documents.parse import ParsedDocument, ParsedElement, parse_pdf
from app.documents.redact import PiiDetector, PiiSpan
from app.documents.sniff import PdfFacts
from app.documents.types import ElementKind, VersionStage

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
RAW_PII = ("Marie Tremblay", "130 692 544", "marie.tremblay@example.com", "514-555-0142")


class NameOnlyDetector:
    def detect(self, text: str) -> list[PiiSpan]:
        start = text.find("Marie Tremblay")
        return [] if start < 0 else [PiiSpan(start, start + len("Marie Tremblay"), "PERSON", 0.9)]


def _fake_parser(_path: Path) -> ParsedDocument:
    return ParsedDocument(
        elements=(
            ParsedElement(ElementKind.heading, "3. Fees", ("3. Fees",), 1, 1),
            ParsedElement(ElementKind.paragraph, "Client Marie Tremblay pays quarterly.", ("3. Fees",), 1, 2),
        ),
        page_grades={1: "GOOD", 2: "EXCELLENT"},
        parser_version="fake 1",
    )


def _stored_version(db_session, tenant_id):
    data = FIXTURE.read_bytes()
    return dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="tremblay-ima", title="Tremblay IMA", source_url=None,
        data=data, facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version


def _run(db_session, version_id, parser=_fake_parser, detector=None):
    parse_and_redact(
        db_session, version_id, parser=parser, detector=detector or NameOnlyDetector(),
        store_root=config.DOCUMENT_STORE_DIR, hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY,
    )


def test_stage_writes_redacted_elements_tokens_and_parsed_event(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id)
    elements = dao.list_elements(db_session, version.id)
    assert [e.ordinal for e in elements] == [0, 1]
    assert "Marie Tremblay" not in elements[1].text_redacted
    assert (elements[1].page_start, elements[1].page_end) == (1, 2)
    events = dao.version_events(db_session, version.id)
    assert [e.stage for e in events] == [VersionStage.stored, VersionStage.parsed]
    assert events[-1].detail["page_grades"] == {"1": "GOOD", "2": "EXCELLENT"}
    assert events[-1].detail["pii_token_count"] == 1


def test_stage_is_a_noop_when_already_parsed(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id)
    _run(db_session, version.id)
    assert len(dao.version_events(db_session, version.id)) == 2


@pytest.mark.slow
def test_real_pipeline_leaves_no_raw_pii_in_elements(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id, parser=parse_pdf, detector=PiiDetector())
    stored_text = "\n".join(e.text_redacted for e in dao.list_elements(db_session, version.id))
    for value in RAW_PII:
        assert value not in stored_text
    assert "Ontario" in stored_text and "0.85%" in stored_text
