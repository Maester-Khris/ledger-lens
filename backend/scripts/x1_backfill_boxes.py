"""X1 backfill: give documents parsed before X1 their element boxes, so verification crops evidence instead of whole
pages. Re-parses each version's PDF locally (Docling) and stores a box only where the re-redacted text equals the
stored element at the same ordinal; anything else keeps the page fallback. Writes element_boxes only (append-only).
The VERIFY stage itself needs no backfill: versions with `extracted` and no `verified` event are picked up by the
worker. Run from backend/, after a pg_dump:  $PYDEV/bin/python scripts/x1_backfill_boxes.py"""
import dataclasses
import json
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session  # noqa: E402

from app import config  # noqa: E402
from app.documents import dao, store  # noqa: E402
from app.documents.parse import ParsedDocument  # noqa: E402
from app.documents.redact import PiiDetector, apply_redaction  # noqa: E402


def backfill_boxes(session: Session, version_id: uuid.UUID, *, parser: Callable[[Path], ParsedDocument],
                   detector: PiiDetector, store_root: Path, hmac_key: str) -> tuple[int, int]:
    """(matched, skipped) for one version. Elements that already have boxes are left alone and not counted."""
    elements = dao.list_elements(session, version_id)
    boxed = dao.element_boxes(session, [e.id for e in elements])
    if elements and len(boxed) == len(elements):
        return 0, 0
    tenant_id = dao.get_document_for_version(session, version_id).tenant_id
    pdf = store.original_path(store_root, dao.get_version(session, version_id).file_sha256)
    session.commit()  # no transaction held open across the parse
    parsed = parser(pdf)
    matched = skipped = 0
    for ordinal, element in enumerate(parsed.elements):
        stored = elements[ordinal] if ordinal < len(elements) else None
        if stored is not None and stored.id in boxed:
            continue
        # Deterministic HMAC tokens: the same raw text redacts to exactly the stored text.
        redacted = apply_redaction(element.text, detector.detect(element.text), tenant_id, hmac_key).text
        if stored is None or not element.boxes or redacted != stored.text_redacted:
            skipped += 1
            continue
        dao.save_boxes(session, stored.id, [dataclasses.asdict(b) for b in element.boxes])
        matched += 1
    session.commit()
    return matched, skipped


def main() -> None:
    from app.documents.parse import parse_pdf
    from app.ledger.db import SessionLocal

    detector = PiiDetector()
    totals = {"versions": 0, "matched": 0, "skipped": 0, "seconds": 0.0}
    started = time.perf_counter()
    with SessionLocal() as session:
        for version_id in dao.all_version_ids(session):
            matched, skipped = backfill_boxes(session, version_id, parser=parse_pdf, detector=detector,
                                              store_root=config.DOCUMENT_STORE_DIR, hmac_key=config.require("PII_HMAC_KEY"))
            totals["versions"] += 1
            totals["matched"] += matched
            totals["skipped"] += skipped
            print(json.dumps({"version_id": str(version_id), "matched": matched, "skipped": skipped}), flush=True)
    totals["seconds"] = round(time.perf_counter() - started, 1)
    print(json.dumps({"totals": totals}))


if __name__ == "__main__":
    main()
