"""Export redacted evidence crops and a blind CSV for labelling (X1).

Run from backend/:  $PYDEV/bin/python scripts/x1_label_export.py --out DIR --seed 42
"""
import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
import csv
from pathlib import Path
import random
import sys
import uuid

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.contracts import dao  # noqa: E402
from app.contracts.crops import redact_image  # noqa: E402
from app.contracts.models import ExtractionRun  # noqa: E402
from app.documents import dao as documents_dao  # noqa: E402
from app.documents import store  # noqa: E402
from app.documents.redact import PiiDetector  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402

_current_run_id: ContextVar[uuid.UUID | None] = ContextVar("_current_run_id", default=None)


def draw_sample(
    population: Sequence[tuple[uuid.UUID, str, str]],
    *,
    seed: int,
    per_class: Mapping[str, int],
) -> list[tuple[uuid.UUID, str, str]]:
    """Draw a stratified random sample of population by field class (A, B, C).

    Per class, draws up to per_class[cls] items using random.Random(seed).sample.
    Within each class, preserves sampled order. Reproducible for same seed.
    """
    rng = random.Random(seed)
    result: list[tuple[uuid.UUID, str, str]] = []
    for cls in ("A", "B", "C"):
        k = per_class.get(cls, 0)
        if k <= 0:
            continue
        class_items = [item for item in population if item[2] == cls]
        if not class_items:
            continue
        n = min(k, len(class_items))
        result.extend(rng.sample(class_items, n))
    return result


def export(
    sample: Sequence[tuple[uuid.UUID, str, str]],
    *,
    out_dir: Path,
    store_root: Path,
    redact: Callable[[Image.Image], Image.Image],
) -> int:
    """Export redacted evidence crops and a blind CSV for labelling.

    The CSV never contains extracted values (blind labelling).
    """
    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    written = 0

    for run_id, path, _cls in sample:
        crop_file = store.crop_path(store_root, run_id, path)
        if not crop_file.exists():
            continue

        item_num = written + 1
        rel_crop = f"crops/{item_num}.png"
        dest_crop = out_dir / rel_crop

        image = Image.open(crop_file)
        token = _current_run_id.set(run_id)
        try:
            redacted = redact(image)
        finally:
            _current_run_id.reset(token)

        redacted.save(dest_crop)
        rows.append({
            "item": item_num,
            "run_id": str(run_id),
            "field_path": path,
            "crop_file": rel_crop,
            "value": "",
        })
        written += 1

    csv_path = out_dir / "labels.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["item", "run_id", "field_path", "crop_file", "value"])
        writer.writeheader()
        writer.writerows(rows)

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="output directory for exported crops and CSV")
    parser.add_argument("--seed", type=int, default=42, help="random seed for stratified sampling")
    parser.add_argument("--a", type=int, default=60, help="sample count for class A")
    parser.add_argument("--b", type=int, default=60, help="sample count for class B")
    parser.add_argument("--c", type=int, default=30, help="sample count for class C")
    args = parser.parse_args()

    detector = PiiDetector()
    hmac_key = config.require("PII_HMAC_KEY")
    vault_key = config.require("PII_VAULT_KEY")

    with SessionLocal() as session:
        population = dao.auto_accepted_fields(session)
        per_class = {"A": args.a, "B": args.b, "C": args.c}
        sample = draw_sample(population, seed=args.seed, per_class=per_class)

        counts = Counter(cls for _, _, cls in sample)
        print(f"Sample drawn: A={counts.get('A', 0)}, B={counts.get('B', 0)}, C={counts.get('C', 0)} (total {len(sample)})")

        run_ids = {r for r, _, _ in sample}
        tenants: dict[uuid.UUID, uuid.UUID] = {}
        for r_id in run_ids:
            run = session.get(ExtractionRun, r_id)
            if run is not None:
                doc = documents_dao.get_document_for_version(session, run.version_id)
                if doc is not None:
                    tenants[r_id] = doc.tenant_id

        def redact(image: Image.Image) -> Image.Image:
            r_id = _current_run_id.get()
            tenant_id = tenants.get(r_id) if r_id else None

            def is_personal(text: str) -> bool:
                if bool(detector.detect(text)):
                    return True
                if tenant_id is not None:
                    return documents_dao.tokenize_known_values(session, tenant_id, text, hmac_key, vault_key) != text
                return False

            return redact_image(image, is_personal)

        written = export(sample, out_dir=args.out, store_root=config.DOCUMENT_STORE_DIR, redact=redact)
        print(f"Exported {written} items to {args.out}")


if __name__ == "__main__":
    main()
