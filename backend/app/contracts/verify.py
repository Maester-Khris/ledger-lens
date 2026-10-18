"""X1 verify stage: an independent second reading of each important field, from the evidence it cites.

Layer 1 re-reads the field's crop with local OCR (no egress, no cost). A result never changes the extracted value;
anything but `agree` routes the field to review (terms.field_status). The pipeline runs this between extract and
index, so a document is searchable only once its values are checked (owner decision: safety first)."""
import re
import time
import uuid
from collections import Counter
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from app.contracts import dao
from app.contracts.agree import Outcome, compare_field, compare_text, normalise_text
from app.contracts.crops import crop, ocr_lines, render_pages
from app.contracts.models import ExtractedField
from app.contracts.terms import verification_path
from app.documents import dao as documents_dao
from app.documents import store
from app.documents.models import DocumentElement
from app.documents.types import Box, VersionStage

# Fields whose value is written in the text, so a local re-read can find it. The four inferred class A enums have
# no such text (vision only, Task 5); class C has no live check (audit sample only).
LAYER1_FIELDS = frozenset({"fee_tiers", "fee_basis", "fund_or_account", "adviser", "effective_date", "client"})
OCR_VERIFIER = f"rapidocr {version('rapidocr')}"
RENDER_DPI = 200
# A rate as billing's parser reads it (fee_text.parse_rate_bps); the band wording is whatever precedes it on the line.
_RATE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|bps\b|bp\b|basis points?\b)", re.I)


def read_local(field_path: str, ocr_text: str, extracted: object) -> object | None:
    """The OCR reading of one field, or None when it is not there (recorded as `unreadable`).

    A fee table is truly re-read (mechanic b): every OCR line holding a rate becomes a band, so billing's parsers
    produce an independent table. Text and dates have no parser to re-read them with, so they are confirmed by
    presence (mechanic a): the extracted value, or a near match, appears in the crop."""
    if verification_path(field_path) == "fee_tiers":
        bands = []
        for line in ocr_text.splitlines():
            matches = list(_RATE.finditer(line))
            if matches and (band_text := line[:matches[-1].start()].strip()):
                bands.append({"band_text": band_text, "rate_text": matches[-1].group(0)})
        return bands or None
    if not isinstance(extracted, str) or not extracted.strip():
        return None
    wanted = normalise_text(extracted)
    words = normalise_text(ocr_text).split()
    if wanted in " ".join(words):
        return extracted
    size = len(wanted.split())
    for start in range(max(len(words) - size + 1, 0)):  # ponytail: O(words × size); crops are a paragraph at most
        window = " ".join(words[start:start + size])
        if compare_text(extracted, window).outcome == "agree":
            return window
    return None


def _evidence(elements: Sequence[DocumentElement], boxes: dict[uuid.UUID, list[dict]], pages: dict[int, Image.Image],
              page_sizes: dict[int, tuple[float, float]], table: bool) -> tuple[list[Image.Image], str]:
    """The crops a field cites, and their kind. An element without a box falls back to its whole pages."""
    images, kind = [], "table" if table else "element"
    for element in elements:
        element_boxes = [Box(**b) for b in boxes.get(element.id, [])]
        if not element_boxes:
            kind = "page"
            images += [pages[p] for p in range(element.page_start, element.page_end + 1)]
        else:
            images += [crop(pages[b.page_no], page_sizes[b.page_no], b) for b in element_boxes]
    return images, kind


def _stack(images: Sequence[Image.Image]) -> Image.Image:
    """One image per field for the reviewer's diff card (and, later, the vision verifier)."""
    width = max(i.width for i in images)
    sheet = Image.new("RGB", (width, sum(i.height for i in images)), "white")
    top = 0
    for image in images:
        sheet.paste(image, (0, top))
        top += image.height
    return sheet


def _checks(fields: Sequence[ExtractedField]) -> dict[str, tuple[object, list[uuid.UUID]]]:
    """verification path -> (extracted value, cited element ids). A fee table is one check over all its bands."""
    checks: dict[str, tuple[object, list[uuid.UUID]]] = {}
    for f in fields:
        path = verification_path(f.field_path)
        if path not in LAYER1_FIELDS or not f.element_ids:
            continue  # nothing cited: the extraction already routed it to review (not grounded)
        if path == "fee_tiers":
            bands, ids = checks.get(path, ([], []))
            checks[path] = ([*bands, f.value], [*ids, *(i for i in f.element_ids if i not in ids)])
        else:
            checks[path] = (f.value, list(f.element_ids))
    return checks


def run_verification(session: Session, version_id: uuid.UUID, *, store_root: Path, hmac_key: str, vault_key: str,
                     vision: object | None = None) -> None:
    """The VERIFY stage runner. Idempotent: a check already recorded for this run is kept, not repeated."""
    run = dao.latest_run(session, version_id)
    if run is None:
        documents_dao.append_event(session, version_id, VersionStage.verified, {"run_id": None})
        session.commit()
        return
    tenant_id = documents_dao.get_document_for_version(session, version_id).tenant_id
    pdf_path = store.original_path(store_root, documents_dao.get_version(session, version_id).file_sha256)
    checks = _checks(dao.run_fields(session, run.id))
    by_id = {e.id: e for e in documents_dao.list_elements(session, version_id)}
    boxes = documents_dao.element_boxes(session, list(by_id))
    texts = {path: documents_dao.reveal(session, tenant_id, [value], vault_key)[0]
             for path, (value, _ids) in checks.items() if isinstance(value, str)}
    session.commit()  # no transaction held open across rendering and OCR

    wanted_pages = {p for _v, ids in checks.values() for i in ids for p in range(by_id[i].page_start, by_id[i].page_end + 1)}
    pages = render_pages(pdf_path, sorted(wanted_pages), dpi=RENDER_DPI)
    page_sizes = {p: (img.width * 72 / RENDER_DPI, img.height * 72 / RENDER_DPI) for p, img in pages.items()}
    crop_dir = store_root / "crops" / str(run.id)
    crop_dir.mkdir(parents=True, exist_ok=True)

    outcomes: Counter[Outcome] = Counter()
    ocr_ms = 0
    for path, (value, ids) in sorted(checks.items()):
        images, kind = _evidence([by_id[i] for i in ids], boxes, pages, page_sizes, table=path == "fee_tiers")
        _stack(images).save(crop_dir / f"{path}.png")  # unredacted, local only: the reviewer sees the real evidence
        started = time.perf_counter()
        ocr_text = "\n".join(line.text for image in images for line in ocr_lines(image))
        latency_ms = round((time.perf_counter() - started) * 1000)
        ocr_ms += latency_ms
        extracted = texts.get(path, value)
        read = read_local(path, ocr_text, extracted)
        comparison = compare_field(path, extracted, read)
        outcome: Outcome = "unreadable" if read is None else comparison.outcome
        stored = documents_dao.tokenize_known_values(session, tenant_id, read, hmac_key, vault_key) \
            if isinstance(read, str) else read
        dao.save_verification(session, dao.VerificationRow(
            run.id, path, "ocr_local", OCR_VERIFIER, kind, stored, outcome, comparison.detail, latency_ms=latency_ms))
        outcomes[outcome] += 1
    documents_dao.append_event(session, version_id, VersionStage.verified, {
        "run_id": str(run.id), "fields_checked": len(checks), "outcomes": dict(outcomes), "ocr_ms": ocr_ms,
    })
    session.commit()
