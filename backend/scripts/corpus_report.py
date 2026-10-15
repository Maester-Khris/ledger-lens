"""Corpus status for the N0 numbers: per document its pipeline state, extraction routing and ingestion time.
Run from backend/:  $PYDEV/bin/python scripts/corpus_report.py   (writes reports/corpus-<date>.json, prints a summary)"""
import json
import statistics
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ledger.db import SessionLocal  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
MANIFEST = BACKEND_DIR / "var" / "samples" / "manifest.json"

# Latest version of each document: last stage reached, seconds from stored to extracted, routing of its latest run.
QUERY = text("""
with latest as (
  select distinct on (d.id) d.document_key, d.title, v.id as version_id
  from documents d join document_versions v on v.document_id = d.id
  order by d.id, v.version desc
), events as (
  select version_id,
         (array_agg(stage::text order by id desc))[1] as last_stage,
         extract(epoch from max(created_at) filter (where stage = 'extracted')
                          - min(created_at) filter (where stage = 'stored')) as seconds
  from version_events group by version_id
), run as (
  select distinct on (version_id) version_id, id from extraction_runs order by version_id, created_at desc
)
select l.document_key, l.title, e.last_stage, e.seconds,
       count(f.*) filter (where f.routing = 'accepted') as accepted,
       count(f.*) filter (where f.routing = 'needs_review') as needs_review
from latest l
left join events e on e.version_id = l.version_id
left join run r on r.version_id = l.version_id
left join extracted_fields f on f.run_id = r.id
group by l.document_key, l.title, e.last_stage, e.seconds
order by l.document_key
""")


def main() -> None:
    relationships = {s["key"]: s.get("relationship") for s in json.loads(MANIFEST.read_text())} if MANIFEST.exists() else {}
    with SessionLocal() as session:
        rows = [dict(r._mapping) for r in session.execute(QUERY)]
    for row in rows:
        row["seconds"] = float(row["seconds"]) if row["seconds"] is not None else None
        row["origin"] = "synthetic" if row["document_key"] == "tremblay-ima" else "edgar"
        row["relationship"] = relationships.get(row["document_key"], "client" if row["origin"] == "synthetic" else None)
    done = [r for r in rows if r["last_stage"] == "extracted"]
    seconds = [r["seconds"] for r in done if r["seconds"] is not None]
    summary = {
        "documents": len(rows),
        "by_state": dict(Counter(r["last_stage"] for r in rows)),
        "by_relationship": dict(Counter(r["relationship"] for r in rows)),
        "by_origin": dict(Counter(r["origin"] for r in rows)),
        "fields_accepted": sum(r["accepted"] for r in done),
        "fields_needs_review": sum(r["needs_review"] for r in done),
        "documents_all_fields_accepted": sum(1 for r in done if r["needs_review"] == 0 and r["accepted"] > 0),
        "queue_to_extracted_seconds_median": statistics.median(seconds) if seconds else None,
        "queue_to_extracted_seconds_max": max(seconds) if seconds else None,
        "limit": "queue_to_extracted includes waiting behind the rest of the batch (one local worker, one stage at a time); throughput is in var/samples/corpus-build.log; cost is in Langfuse, tag extraction",
    }
    out = BACKEND_DIR / "reports" / f"corpus-{date.today()}.json"
    out.write_text(json.dumps({"summary": summary, "documents": rows}, indent=2, default=str))
    print(json.dumps(summary, indent=2))
    for r in rows:
        if r["last_stage"] != "extracted":
            print(f"  not extracted: {r['document_key']} ({r['last_stage']})")
    print(f"written {out.relative_to(BACKEND_DIR)}")


if __name__ == "__main__":
    main()
