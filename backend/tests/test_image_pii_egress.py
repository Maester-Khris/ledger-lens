"""X1 image egress (spec section 6, owner decision 3): personal data is removed from images before anything leaves the
machine. Every crop of the fixture, and every whole page (the fallback when an element has no box), is blacked out
the way the vision verifier will do it, then OCR'd again: no known raw value may remain readable."""
from pathlib import Path

import pytest
from PIL import Image

from app import config
from app.contracts.crops import crop, ocr_lines, redact_image, render_pages
from app.documents import dao as documents_dao
from app.documents.ingest import parse_and_redact
from app.documents.parse import parse_pdf
from app.documents.redact import PiiDetector
from app.documents.sniff import PdfFacts
from app.documents.types import Box

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
RAW_PII = ("Marie Tremblay", "Tremblay", "130 692 544", "marie.tremblay@example.com", "514-555-0142",
           "1450 Rue Sherbrooke")
LETTER = (612.0, 792.0)


def _readable(image: Image.Image) -> str:
    return " ".join(line.text for line in ocr_lines(image))


@pytest.fixture(scope="module")
def detector() -> PiiDetector:
    return PiiDetector()


@pytest.fixture()
def ingested(db_session, tenant_id, detector):
    data = FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="x1-egress", title="Tremblay IMA", source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version
    parse_and_redact(db_session, version.id, parser=parse_pdf, detector=detector, store_root=config.DOCUMENT_STORE_DIR,
                     hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY)

    def is_personal(text: str) -> bool:
        known = documents_dao.tokenize_known_values(db_session, tenant_id, text, config.PII_HMAC_KEY, config.PII_VAULT_KEY)
        return bool(detector.detect(text)) or known != text

    return version, is_personal


def test_redact_image_blacks_out_only_personal_lines():
    page = render_pages(FIXTURE, [1])[1]
    redacted = redact_image(page, lambda text: "Tremblay" in text)
    text = _readable(redacted)
    assert "Tremblay" not in text
    assert "Maple Ridge Wealth Advisors" in text  # business data stays readable for the verifier


@pytest.mark.slow
def test_no_raw_pii_in_any_redacted_crop(db_session, ingested):
    version, is_personal = ingested
    pages = render_pages(FIXTURE, [1, 2])
    elements = documents_dao.list_elements(db_session, version.id)
    boxes = documents_dao.element_boxes(db_session, [e.id for e in elements])
    leaks = []
    for element in elements:
        for raw_box in boxes.get(element.id, []):
            box = Box(**raw_box)
            text = _readable(redact_image(crop(pages[box.page_no], LETTER, box), is_personal))
            leaks += [(element.ordinal, value) for value in RAW_PII if value in text]
    assert leaks == []


@pytest.mark.slow
def test_page_fallback_crop_has_no_raw_pii(ingested):
    _version, is_personal = ingested
    for page_no, page in render_pages(FIXTURE, [1, 2]).items():
        text = _readable(redact_image(crop(page, LETTER, None), is_personal))
        assert [value for value in RAW_PII if value in text] == [], page_no
