"""X1 backfill (spec section 8): documents parsed before X1 get their element boxes by re-parsing, matched on
(version, ordinal) only when the re-redacted text is identical to what is stored."""
from pathlib import Path

from app import config
from app.documents import dao
from app.documents.parse import ParsedDocument, ParsedElement
from app.documents.types import Box, ElementKind
from scripts.x1_backfill_boxes import backfill_boxes
from tests.test_documents_ingest import NameOnlyDetector, _run, _stored_version

BOX = Box(1, 72, 700, 540, 650, "BOTTOMLEFT")


def _reparse(texts: tuple[str, ...], boxes: tuple[Box, ...] = (BOX,)):
    def parser(_path: Path) -> ParsedDocument:
        return ParsedDocument(
            elements=tuple(ParsedElement(ElementKind.paragraph, t, ("3. Fees",), 1, 1, boxes) for t in texts),
            page_grades={1: "GOOD"}, parser_version="fake 2")
    return parser


PRE_X1 = _reparse(("3. Fees", "Client Marie Tremblay pays quarterly."), boxes=())  # parsed before boxes existed


def _backfill(db_session, version_id, parser):
    return backfill_boxes(db_session, version_id, parser=parser, detector=NameOnlyDetector(),
                          store_root=config.DOCUMENT_STORE_DIR, hmac_key=config.PII_HMAC_KEY)


def test_backfill_matches_only_identical_text(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id, parser=PRE_X1)
    # the heading now parses differently; the paragraph is the same (its client name re-redacts to the same token)
    assert _backfill(db_session, version.id, _reparse(("3. Fees and charges", "Client Marie Tremblay pays quarterly."))) == (1, 1)
    elements = dao.list_elements(db_session, version.id)
    boxes = dao.element_boxes(db_session, [e.id for e in elements])
    assert elements[0].id not in boxes  # a mismatch keeps the page fallback rather than a wrong box
    assert boxes[elements[1].id] == [{"page_no": 1, "l": 72, "t": 700, "r": 540, "b": 650, "coord_origin": "BOTTOMLEFT"}]


def test_backfill_is_idempotent_and_ignores_extra_elements(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id, parser=PRE_X1)
    parser = _reparse(("3. Fees", "Client Marie Tremblay pays quarterly.", "A new paragraph Docling now finds."))
    assert _backfill(db_session, version.id, parser) == (2, 1)
    assert _backfill(db_session, version.id, parser) == (0, 0)  # fully boxed: not even re-parsed
