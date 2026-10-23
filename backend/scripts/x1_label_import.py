"""Import ground-truth labels from CSV into field_labels table (X1).

Run from backend/:  $PYDEV/bin/python scripts/x1_label_import.py labels.csv --labeller human:niki
"""
import argparse
import csv
import json
from pathlib import Path
import re
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import dao  # noqa: E402
from app.contracts.dao import LabelRow  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402

_LABELLER_PATTERN = re.compile(r"^(human:.+|judge:.+|adjudicated)$")


def read_labels(csv_path: Path, labeller: str, blind: bool = True) -> list[LabelRow]:
    """Parse a CSV of labels into LabelRow objects for insertion into field_labels.

    Validates labeller format and ensures non-empty values. JSON-encoded values
    (numbers, lists, null) are parsed; otherwise the value is kept as a raw string.
    """
    if not _LABELLER_PATTERN.match(labeller):
        raise ValueError(f"Invalid labeller '{labeller}'; must match 'human:<name>', 'judge:<model>', or 'adjudicated'")

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows: list[LabelRow] = []
        for row in reader:
            item = row.get("item", "")
            raw_val = row.get("value", "")
            stripped = raw_val.strip() if raw_val is not None else ""
            if not stripped:
                raise ValueError(f"item {item}: empty value")

            try:
                parsed_val = json.loads(stripped)
            except json.JSONDecodeError:
                parsed_val = stripped

            rows.append(LabelRow(
                run_id=uuid.UUID(row["run_id"]),
                field_path=row["field_path"],
                labeller=labeller,
                label_value=parsed_val,
                blind=blind,
            ))
        return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, help="CSV file containing labels")
    parser.add_argument("--labeller", required=True, help="labeller identity (human:<name>, judge:<model>, or adjudicated)")
    parser.add_argument("--not-blind", action="store_true", help="mark labels as not blind (blind by default)")
    args = parser.parse_args()

    rows = read_labels(args.csv, args.labeller, blind=not args.not_blind)
    with SessionLocal() as session:
        dao.save_labels(session, rows)
        session.commit()
    print(f"Imported {len(rows)} labels for '{args.labeller}' from {args.csv}")


if __name__ == "__main__":
    main()
