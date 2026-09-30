"""Field accuracy of the served terms on ledger_dev (samples ingested and extracted by the worker).
Run: $PYDEV/bin/pytest -m eval tests/eval/test_extraction.py -s"""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.contracts import dao as contracts_dao
from app.documents.models import Document
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID

TRUTH = json.loads((Path(__file__).parent / "extraction_truth.json").read_text())


@pytest.mark.eval
def test_extraction_field_accuracy():
    checked, correct, report = 0, 0, {}
    with SessionLocal() as session:
        for key, truth in TRUTH.items():
            document = session.scalars(select(Document).where(Document.tenant_id == DEMO_TENANT_ID, Document.document_key == key)).one()
            served = contracts_dao.served_fields(session, DEMO_TENANT_ID, document.id)
            fields = {} if served is None else {p: f.value for p, f in served.fields.items()}
            got_tiers = [[fields[p]["up_to_minor"], format(Decimal(fields[p]["rate_bps"]).normalize(), "f")]
                         for p in sorted((p for p in fields if p.startswith("fee_tiers[")), key=lambda p: int(p[10:-1]))]
            expected_tiers = [[u, format(Decimal(r).normalize(), "f")] for u, r in truth["tiers"]]
            checks = {"fee_method": fields.get("fee_method") == truth["fee_method"],
                      "currency": fields.get("currency") == truth["currency"], "tiers": got_tiers == expected_tiers}
            report[key] = checks | {"unserved": [] if served is None else served.unserved}
            checked += len(checks)
            correct += sum(checks.values())
    print(json.dumps(report, indent=2), f"\nfield accuracy: {correct}/{checked}")
    assert checked  # record the real number as-is; a miss here is review work, not a broken build
