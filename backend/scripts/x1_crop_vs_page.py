"""Compare vision verifier accuracy on isolated crops vs full rendered pages (X1).

Run from backend/:  $PYDEV/bin/python scripts/x1_crop_vs_page.py
Note: Judges are paid calls the owner approves first.
"""
import argparse
from collections.abc import Mapping, Sequence
import io
import json
from pathlib import Path
import sys

from PIL import Image
from langchain_openai import ChatOpenAI
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.contracts import dao  # noqa: E402
from app.contracts.agree import compare_field  # noqa: E402
from app.contracts.crops import redact_image, render_pages  # noqa: E402
from app.contracts.models import ExtractionRun, FieldLabel  # noqa: E402
from app.contracts.terms import field_class, verification_path  # noqa: E402
from app.contracts.verify import VisionRequest, VisionVerifier  # noqa: E402
from app.documents import dao as documents_dao  # noqa: E402
from app.documents import store  # noqa: E402
from app.documents.redact import PiiDetector  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402


def crop_vs_page(items: Sequence[Mapping], verifier: VisionVerifier) -> dict:
    """Evaluate vision verifier accuracy on isolated crops vs full rendered pages.

    Reads all crops in one batch, then all pages in a second batch.
    """
    n = len(items)
    if n == 0:
        return {
            "n": 0,
            "crop": {"correct": 0, "accuracy": 0.0},
            "page": {"correct": 0, "accuracy": 0.0},
        }

    crop_requests = [VisionRequest(field_path=item["field_path"], image_png=item["crop_png"]) for item in items]
    crop_readings = verifier.read(crop_requests)

    page_requests = [VisionRequest(field_path=item["field_path"], image_png=item["page_png"]) for item in items]
    page_readings = verifier.read(page_requests)

    c = 0
    for item, reading in zip(items, crop_readings):
        if reading.failed is None:
            comparison = compare_field(item["field_path"], item["label"], reading.value)
            if comparison.outcome == "agree":
                c += 1

    p = 0
    for item, reading in zip(items, page_readings):
        if reading.failed is None:
            comparison = compare_field(item["field_path"], item["label"], reading.value)
            if comparison.outcome == "agree":
                p += 1

    return {
        "n": n,
        "crop": {"correct": c, "accuracy": c / n},
        "page": {"correct": p, "accuracy": p / n},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=config.BACKEND_DIR / "reports" / "x1-crop-vs-page.json",
        help="output JSON report path",
    )
    args = parser.parse_args()

    detector = PiiDetector()
    hmac_key = config.require("PII_HMAC_KEY")
    vault_key = config.require("PII_VAULT_KEY")

    items: list[dict] = []
    with SessionLocal() as session:
        # Load labelled class A items (labeller adjudicated, else first human labeller)
        all_labels = session.scalars(select(FieldLabel).order_by(FieldLabel.created_at)).all()
        by_key: dict[tuple, list[FieldLabel]] = {}
        for l in all_labels:
            if field_class(l.field_path) == "A":
                by_key.setdefault((l.run_id, l.field_path), []).append(l)

        for (run_id, field_path), group in by_key.items():
            adj = next((l for l in group if l.labeller == "adjudicated"), None)
            if adj is not None:
                chosen = adj
            else:
                human = next((l for l in group if l.labeller.startswith("human:")), None)
                if human is not None:
                    chosen = human
                else:
                    continue

            crop_file = store.crop_path(config.DOCUMENT_STORE_DIR, run_id, field_path)
            if not crop_file.exists():
                continue
            crop_img = Image.open(crop_file)

            run = session.get(ExtractionRun, run_id)
            if run is None:
                continue

            doc = documents_dao.get_document_for_version(session, run.version_id)
            if doc is None:
                continue
            tenant_id = doc.tenant_id

            version = documents_dao.get_version(session, run.version_id)
            pdf_path = store.original_path(config.DOCUMENT_STORE_DIR, version.file_sha256)

            run_fields = dao.run_fields(session, run_id)
            if field_path == "fee_tiers":
                eids = [eid for f in run_fields if verification_path(f.field_path) == "fee_tiers" for eid in f.element_ids]
            else:
                eids = [eid for f in run_fields if f.field_path == field_path for eid in f.element_ids]

            if not eids:
                continue

            first_pg = documents_dao.first_page(session, eids)
            if first_pg is None:
                continue

            rendered_pages = render_pages(pdf_path, [first_pg], dpi=200)
            page_img = rendered_pages[first_pg]

            def is_personal(text: str) -> bool:
                return bool(detector.detect(text)) or (
                    documents_dao.tokenize_known_values(session, tenant_id, text, hmac_key, vault_key) != text
                )

            redacted_crop = redact_image(crop_img, is_personal)
            redacted_page = redact_image(page_img, is_personal)

            crop_buf = io.BytesIO()
            redacted_crop.save(crop_buf, format="PNG")
            crop_bytes = crop_buf.getvalue()

            page_buf = io.BytesIO()
            redacted_page.save(page_buf, format="PNG")
            page_bytes = page_buf.getvalue()

            items.append({
                "field_path": field_path,
                "label": chosen.label_value,
                "crop_png": crop_bytes,
                "page_png": page_bytes,
            })

    chat_model = ChatOpenAI(
        model=config.VERIFIER_MODEL,
        reasoning_effort="none",
        timeout=config.VERIFIER_TIMEOUT_SECONDS,
        max_retries=config.LLM_MAX_RETRIES,
    )
    verifier = VisionVerifier(chat_model, config.VERIFIER_MODEL)
    report = crop_vs_page(items, verifier)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
