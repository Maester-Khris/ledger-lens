"""X1 verify stage: an independent second reading of each important field, from the evidence it cites.

Layer 1 re-reads the field's crop with local OCR (no egress, no cost). A result never changes the extracted value;
anything but `agree` routes the field to review (terms.field_status). The pipeline runs this between extract and
index, so a document is searchable only once its values are checked (owner decision: safety first).

Layer 2 adds a vision model reading redacted crops of class A fields, never seeing the extracted value."""
import base64
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from importlib.metadata import version
import io
from pathlib import Path
import random
import re
import time
from typing import Any, Literal
import uuid

from PIL import Image
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import config
from app.contracts import dao
from app.contracts.agree import Outcome, compare_field, compare_text, normalise_text
from app.contracts.fee_text import FeeTextError, parse_amount_minor, parse_rate_bps
from app.contracts.crops import crop, ocr_lines, redact_image, render_pages
from app.contracts.models import ExtractedField
from app.contracts.terms import verification_path
from app.documents import dao as documents_dao
from app.documents import store
from app.documents.models import DocumentElement
from app.documents.redact import PiiDetector
from app.documents.types import Box, VersionStage

# Fields whose value is written in the text, so a local re-read can find it. The four inferred class A enums have
# no such text (vision only, Task 5); class C has no live check (audit sample only).
LAYER1_FIELDS = frozenset({"fee_tiers", "fee_basis", "fund_or_account", "adviser", "effective_date", "client"})
# The rules version is part of the verifier's identity: a re-check under new rules appends rows, never overwrites.
OCR_VERIFIER = f"rapidocr {version('rapidocr')} rules-v2"
RENDER_DPI = 200
# A rate as billing's parser reads it (fee_text.parse_rate_bps); the band wording is whatever precedes it on the line.
_RATE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|bps\b|bp\b|basis points?\b)", re.I)

INFERRED_FIELDS = frozenset({"fee_method", "currency", "billing_frequency", "payment_timing"})
FEE_SECTION_FIELDS = frozenset({"fee_tiers", "fee_basis", "fee_method", "currency", "billing_frequency", "payment_timing"})
CLASS_A_FIELDS = frozenset({"fee_tiers", "fee_basis", "fee_method", "currency", "billing_frequency", "payment_timing"})
CLASS_B_FIELDS = frozenset({"adviser", "fund_or_account", "effective_date"})
ALL_VERIFY_FIELDS = LAYER1_FIELDS | CLASS_A_FIELDS | CLASS_B_FIELDS
MAX_DETAIL_CHARS = 500  # a provider error message is stored for the reviewer, bounded like pipeline errors
VISION_SAMPLE_RATE = 0.10  # ponytail, a fixed audit rate; tune with labels

PROMPT_ID = "verify_v2"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_ID}.md"
PROMPT = PROMPT_PATH.read_text(encoding="utf-8").strip()

_FIELD_DESCRIPTIONS: dict[str, str] = {
    "fee_tiers": "Every band's wording and rate, in order; null if the image shows no fee table.",
    "fee_basis": "What the fee is calculated on or charged against; null if not stated.",
    # The four inferred fields: the excerpt is the whole fee section, and the rules say what the wording implies.
    "fee_method": "graduated when the schedule has bands billed at their own rates ('first ... next ... in excess of'); "
                  "cliff when one rate applies to all assets; null if the excerpt shows no fee schedule.",
    "currency": "The currency of the fees: USD when amounts are written with $ and no other currency is named, CAD "
                "when Canadian dollars are named; null if the excerpt shows no amount or currency.",
    "billing_frequency": "How often the fee is billed or paid (monthly, quarterly, annually), as the fee section "
                         "states it; null if not stated.",
    "payment_timing": "arrears when the fee is paid after the period it covers (in arrears, at the end of each period); "
                      "advance when paid before; null if not stated.",
    "adviser": "The legal name of the investment adviser or manager; null if not stated.",
    "fund_or_account": "The fund, account, or portfolio name; null if not stated.",
    "effective_date": "The effective date of the agreement as written; null if not stated.",
}


@dataclass(frozen=True)
class VisionRequest:
    field_path: str  # the verification path: "fee_tiers" for the whole table
    image_png: bytes  # already redacted
    hint: str | None = None  # for a fee table, the fund whose schedule to read; never the value being checked


@dataclass(frozen=True)
class VisionReading:
    value: object | None  # the model's reading, in the field's own shape; None = "not stated"
    failed: str | None  # error text when the call failed or the output did not parse; then value is None
    input_tokens: int
    output_tokens: int
    latency_ms: int


class Band(BaseModel):
    band_text: str
    rate_text: str


class FeeTiersReading(BaseModel):
    value: list[Band] | None = None


class FeeMethodReading(BaseModel):
    value: Literal["graduated", "cliff"] | None = None


class CurrencyReading(BaseModel):
    value: Literal["USD", "CAD"] | None = None


class BillingFrequencyReading(BaseModel):
    value: Literal["monthly", "quarterly", "annually"] | None = None


class PaymentTimingReading(BaseModel):
    value: Literal["arrears", "advance"] | None = None


class IntReading(BaseModel):
    value: int | None = None


class TextReading(BaseModel):
    value: str | None = None


def _schema_for(field_path: str) -> type[BaseModel]:
    match field_path:
        case "fee_tiers":
            return FeeTiersReading
        case "fee_method":
            return FeeMethodReading
        case "currency":
            return CurrencyReading
        case "billing_frequency":
            return BillingFrequencyReading
        case "payment_timing":
            return PaymentTimingReading
        case "termination_notice_days":
            return IntReading
        case _:
            return TextReading


class VisionVerifier:
    def __init__(self, chat_model: BaseChatModel, model_id: str) -> None:
        self.chat_model = chat_model
        self.model_id = model_id

    def read(self, requests: Sequence[VisionRequest]) -> list[VisionReading]:
        """Read evidence images for requests, returning readings in the same order."""
        if not requests:
            return []

        def _invoke_one(req: VisionRequest) -> tuple[dict, int]:
            schema = _schema_for(req.field_path)
            desc = _FIELD_DESCRIPTIONS.get(
                req.field_path,
                f"Read the value of {req.field_path} as written; null if not stated."
            )
            b64_img = base64.b64encode(req.image_png).decode("ascii")
            messages: list[BaseMessage] = [
                SystemMessage(content=PROMPT),
                HumanMessage(content=[
                    {"type": "text", "text": f"field: {req.field_path}\n{desc}"
                     + (f"\nRead the schedule that applies to: {req.hint}" if req.hint else "")},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
                ]),
            ]
            t0 = time.perf_counter()
            call = self.chat_model.with_structured_output(schema, method="json_schema", include_raw=True)
            res = call.invoke(messages)
            latency_ms = round((time.perf_counter() - t0) * 1000)
            return res, latency_ms

        batch_results = RunnableLambda(_invoke_one).batch(
            list(requests),
            config={"max_concurrency": config.VERIFIER_CONCURRENCY},
            return_exceptions=True,
        )

        readings: list[VisionReading] = []
        for item in batch_results:
            if isinstance(item, Exception):
                readings.append(VisionReading(
                    value=None,
                    failed=str(item) or type(item).__name__,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                ))
                continue

            res, latency_ms = item
            raw = res.get("raw") if isinstance(res, dict) else None
            usage = getattr(raw, "usage_metadata", None) or {}
            if not isinstance(usage, dict):
                usage = getattr(usage, "__dict__", {})
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)

            parsed = res.get("parsed") if isinstance(res, dict) else None
            if parsed is None:
                err = res.get("parsing_error") if isinstance(res, dict) else None
                failed = str(err) if err else "unparseable output"
                readings.append(VisionReading(
                    value=None,
                    failed=failed,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                ))
            else:
                val = parsed.get("value") if isinstance(parsed, dict) else getattr(parsed, "value", None)
                if isinstance(val, list):
                    val = [b.model_dump() if hasattr(b, "model_dump") else b for b in val]
                readings.append(VisionReading(
                    value=val,
                    failed=None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                ))

        return readings


def _line_bands(ocr_text: str) -> list[dict[str, str]]:
    """Every (wording, rate) pair the OCR lines hold; a multi-column line can hold several rates."""
    bands = []
    for line in ocr_text.splitlines():
        start = 0
        for match in _RATE.finditer(line):
            if band_text := line[start:match.start()].strip():
                bands.append({"band_text": band_text, "rate_text": match.group(0)})
            start = match.end()
    return bands


def _read_bands(ocr_text: str, extracted: Sequence[Mapping]) -> list[dict[str, str]] | None:
    """For each extracted band, the OCR band with the same rate and the same amount (billing's parsers), in order.
    Presence per band, not a re-read of the whole table: corpus tables often list several funds, and the other funds'
    rows must not count as extra bands. A band that is not found is left out, so the comparison disagrees."""
    found = []
    candidates = _line_bands(ocr_text)
    for band in extracted:
        try:
            rate = parse_rate_bps(str(band.get("rate_text", "")))
        except FeeTextError:
            continue
        amount = parse_amount_minor(str(band.get("band_text", "")))
        for candidate in candidates:
            try:
                same_rate = parse_rate_bps(candidate["rate_text"]) == rate
            except FeeTextError:
                continue
            if same_rate and parse_amount_minor(candidate["band_text"]) == amount:
                found.append(candidate)
                candidates.remove(candidate)
                break
    return found or None


def read_local(field_path: str, ocr_text: str, extracted: object) -> object | None:
    """The OCR reading of one field, or None when it is not there (recorded as `unreadable`).

    Everything is confirmed by presence (mechanic a): each fee band's rate and amount on one OCR line (a whole-table
    re-read counted other funds' rows on multi-fund tables, measured on the corpus 2026-10-18), and text or dates as
    the extracted value, or a near match, in the crop."""
    if verification_path(field_path) == "fee_tiers":
        return _read_bands(ocr_text, extracted if isinstance(extracted, list) else [])
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
        if path not in ALL_VERIFY_FIELDS or not f.element_ids:
            continue  # nothing cited: the extraction already routed it to review (not grounded)
        if path == "fee_tiers":
            bands, ids = checks.get(path, ([], []))
            checks[path] = ([*bands, f.value], [*ids, *(i for i in f.element_ids if i not in ids)])
        else:
            checks[path] = (f.value, list(f.element_ids))
    return checks


def run_verification(session: Session, version_id: uuid.UUID, *, store_root: Path, hmac_key: str, vault_key: str,
                     vision: VisionVerifier | None = None, detector: PiiDetector | None = None,
                     only: frozenset[str] | None = None, record_event: bool = True) -> None:
    """The VERIFY stage runner. Idempotent: a check already recorded for this run is kept, not repeated.

    `only` limits the checks to these verification paths and `record_event=False` skips the `verified` event: both
    serve re-checks of existing runs under new rules or a new prompt (new verifier ids append rows; the newest wins)."""
    run = dao.latest_run(session, version_id)
    if run is None:
        documents_dao.append_event(session, version_id, VersionStage.verified, {"run_id": None})
        session.commit()
        return
    tenant_id = documents_dao.get_document_for_version(session, version_id).tenant_id
    pdf_path = store.original_path(store_root, documents_dao.get_version(session, version_id).file_sha256)
    fields = dao.run_fields(session, run.id)
    checks = _checks(fields)
    by_id = {e.id: e for e in documents_dao.list_elements(session, version_id)}
    # An inferred field has no wording of its own to crop: its evidence is the whole fee section, in page order.
    fee_section = sorted({i for path in FEE_SECTION_FIELDS if path in checks for i in checks[path][1]},
                         key=lambda i: by_id[i].ordinal)
    for path in INFERRED_FIELDS & checks.keys():
        checks[path] = (checks[path][0], fee_section)
    if only is not None:
        checks = {path: check for path, check in checks.items() if path in only}
    fund = next((f.value for f in fields if f.field_path == "fund_or_account" and isinstance(f.value, str)), None)
    fund_text = documents_dao.reveal(session, tenant_id, [fund], vault_key)[0] if fund else None
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
    layer1_outcomes: dict[str, Outcome] = {}
    crops: dict[str, tuple[Image.Image, str]] = {}

    for path, (value, ids) in sorted(checks.items()):
        images, kind = _evidence([by_id[i] for i in ids], boxes, pages, page_sizes, table=path == "fee_tiers")
        stacked = _stack(images)
        stacked.save(store.crop_path(store_root, run.id, path))  # unredacted, local only: the reviewer sees the real evidence
        crops[path] = (stacked, kind)

        if path in LAYER1_FIELDS:
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
            layer1_outcomes[path] = outcome

    vision_outcomes: Counter[Outcome] = Counter()
    vision_ms = 0
    total_cost_usd = Decimal(0)

    if vision is not None:
        if detector is None:
            detector = PiiDetector()

        def is_personal(text: str) -> bool:
            return bool(detector.detect(text)) or (
                documents_dao.tokenize_known_values(session, tenant_id, text, hmac_key, vault_key) != text
            )

        vision_requests: list[VisionRequest] = []
        vision_meta: list[tuple[str, str, object]] = []

        for path, (value, ids) in sorted(checks.items()):
            if path == "client":
                # Owner decision: client personal data never goes to vision model
                continue

            should_verify = False
            if path in CLASS_A_FIELDS:
                should_verify = True
            elif path in CLASS_B_FIELDS:
                l1_outcome = layer1_outcomes.get(path)
                if l1_outcome != "agree":
                    should_verify = True
                elif random.Random(f"{run.id}:{path}").random() < VISION_SAMPLE_RATE:
                    # ponytail, a fixed audit rate; tune with labels
                    should_verify = True

            if should_verify:
                stacked, kind = crops[path]
                redacted = redact_image(stacked, is_personal)
                buf = io.BytesIO()
                redacted.save(buf, format="PNG")
                # The fund names which schedule to read on a multi-fund table; never sent if it is personal data.
                hint = fund_text if path == "fee_tiers" and fund_text and not is_personal(fund_text) else None
                vision_requests.append(VisionRequest(field_path=path, image_png=buf.getvalue(), hint=hint))
                extracted = texts.get(path, value)
                vision_meta.append((path, kind, extracted))

        session.commit()  # no transaction held open across the provider calls (up to the timeout each)
        readings = vision.read(vision_requests)
        in_price, out_price = config.VERIFIER_PRICE_PER_MTOK

        for (path, kind, extracted), reading in zip(vision_meta, readings):
            vision_ms += reading.latency_ms
            cost_usd = (
                Decimal(reading.input_tokens) * in_price / Decimal(1_000_000)
                + Decimal(reading.output_tokens) * out_price / Decimal(1_000_000)
            ).quantize(Decimal("0.000001"))
            total_cost_usd += cost_usd

            if reading.failed is not None:
                outcome = "error"
                detail = reading.failed[:MAX_DETAIL_CHARS]
                stored = None
            else:
                comparison = compare_field(path, extracted, reading.value)
                outcome = comparison.outcome
                detail = comparison.detail
                stored = (
                    documents_dao.tokenize_known_values(session, tenant_id, reading.value, hmac_key, vault_key)
                    if isinstance(reading.value, str)
                    else reading.value
                )

            dao.save_verification(
                session,
                dao.VerificationRow(
                    run.id,
                    path,
                    "vision",
                    f"{vision.model_id}@{PROMPT_ID}",
                    kind,
                    stored,
                    outcome,
                    detail,
                    input_tokens=reading.input_tokens,
                    output_tokens=reading.output_tokens,
                    cost_usd=cost_usd,
                    latency_ms=reading.latency_ms,
                ),
            )
            vision_outcomes[outcome] += 1

    event_detail: dict[str, Any] = {
        "run_id": str(run.id),
        "fields_checked": len(checks),
        "outcomes": dict(outcomes),
        "ocr_ms": ocr_ms,
    }
    if vision is not None:
        event_detail["vision_outcomes"] = dict(vision_outcomes)
        event_detail["vision_ms"] = vision_ms
        event_detail["cost_usd"] = float(total_cost_usd)

    if record_event:
        documents_dao.append_event(session, version_id, VersionStage.verified, event_detail)
    session.commit()
