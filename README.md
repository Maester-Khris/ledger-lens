# Fintech Ledger + Document Intelligence

A double-entry ledger core (idempotent postings, balance-invariant
enforcement, compensating reversals) paired with a document-intelligence
chat feature (OCR ingestion, retrieval-augmented Q&A with citations, and
agentic tool-calls back into the ledger).

Full scope and phased execution plan: [artifacts/product-backlog.md](artifacts/product-backlog.md).
See [`CHANGELOG.md`](./CHANGELOG.md) for what's shipped so far, sprint by sprint.

**Status:** ledger DB core (Epic 1.1 schema/migrations + Epic 1.2 balance
invariant enforcement) implemented, database side only — see
[docs/superpowers/specs/2026-09-06-ledger-db-schema-design.md](docs/superpowers/specs/2026-09-06-ledger-db-schema-design.md).
No REST API, concurrency stress test, or deployment yet.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| Frontend | React (Vite) |
| DB | PostgreSQL + pgvector (not wired up yet) |

## Running the backend

The backend runs in a Python 3.12 env of your choice (`$PYDEV`, its root directory), not a repo-local `.venv`.
Set it once per shell (or as `PYDEV=` in `backend/.env`); every command below uses it:

```bash
export PYDEV=/path/to/your/python-env
cd backend
$PYDEV/bin/pip install -r requirements.txt
$PYDEV/bin/pip check   # shared env: confirm the pins didn't break another project's packages
$PYDEV/bin/uvicorn app.main:app --reload
```

Health check: `GET http://127.0.0.1:8000/health`

### Document-intelligence models (one-time download)

Document parsing and PII detection run **locally**. Document content never
leaves the machine; only redacted text reaches the LLM. Both libraries need
model files that pip does not install, so fetch them once after
`pip install`. They arrive with the ingestion phase (`docling`,
`presidio-analyzer` and `presidio-anonymizer` in `requirements.txt`):

```bash
cd backend
# Docling layout and table-structure models (~1 GB): turn a PDF into headings, paragraphs and tables with page numbers.
$PYDEV/bin/docling-tools models download
# spaCy English model used by Presidio's analyzer to detect names (~40 MB, ~150 MB in RAM). The medium model:
# name detection is on par with the large one, which only adds word vectors Presidio doesn't use.
$PYDEV/bin/python -m spacy download en_core_web_md
```

Without them, the first upload either downloads the models mid-request
(Docling) or fails to start the PII analyzer (Presidio). Downloading them up
front keeps ingestion predictable and able to run offline.

### Document ingestion (local run)

1. Set `PII_HMAC_KEY` and `PII_VAULT_KEY` in `backend/.env` (generation commands are in `.env.example`).
2. Start the API: `$PYDEV/bin/uvicorn app.main:app --reload`
3. Start the worker in a second terminal: `$PYDEV/bin/python scripts/ingestion_worker.py`
   (the only process that loads Docling and spaCy; the API stays light)
4. Load the samples: `SEC_USER_AGENT="Name email" $PYDEV/bin/python scripts/prepare_samples.py --upload http://127.0.0.1:8000`
   — three single-fund EDGAR advisory agreements (rendered to PDF so every citation has a page)
   plus the synthetic Tremblay agreement (PII + a deliberate fee mismatch with the seeded billing schedule).
5. Watch status: `curl -s http://127.0.0.1:8000/documents | python -m json.tool`

Scanned PDFs (no text layer) and non-PDF files are rejected at upload with a 422.
Multi-fund EDGAR exhibits are out of scope for now: the extraction schema models one fee schedule per contract.

### Chat (local run)

1. Once: `$PYDEV/bin/python scripts/create_pinecone_index.py` (1536-dim cosine serverless index).
2. With API + worker running and samples ingested, `cd frontend && npm run dev`, open `/chat`.
3. Golden set (real OpenAI + Pinecone, costs cents): `$PYDEV/bin/pytest -m eval tests/eval -s` → `backend/reports/eval-<config>.json`.
   Use it to calibrate `MIN_DENSE_SIMILARITY` in `backend/.env`: the lowest score among correct dense-only hits,
   minus a margin, and above the best score for `not-in-corpus`.

The agent runs in the API process and streams over SSE (progress events, then one verified answer). The upgrade path —
worker + Postgres checkpointer + `LISTEN/NOTIFY` + reconnect from a cursor — is recorded in `artifacts/product-backlog.md`.

### Live run results (2026-09-24, real OpenAI + Pinecone)

Everything above was first built against fakes (268 automated tests). With the real keys in `backend/.env`:

- **Ingestion + extraction** (`gpt-4.1-2025-04-14`, `text-embedding-3-small`, Pinecone serverless `aws/us-east-1`):
  all four sample contracts parsed, indexed and extracted. The synthetic Tremblay agreement had 18/18 fields accepted,
  including its three tiers (100 / 85 / 65 bps). The three EDGAR contracts had 43 of 58 fields accepted; the other 15
  were routed to `needs_review` (missing clauses, non-verbatim quotes, one unparsed date), never served as facts.
- **Golden set** (8 questions, [`backend/reports/eval-fdfec82a79e3.json`](backend/reports/eval-fdfec82a79e3.json)):
  numbers correct **1.0**, refusals correct **0.875**, citation on the expected page **0.875**. The Tremblay leakage
  question returns the **$400.00** annual gap from `compare_contract_to_billing`: the model looks up the document id,
  deterministic code does the arithmetic, and the model only narrates the result. The first live run
  ([`eval-7112ef3432ef.json`](backend/reports/eval-7112ef3432ef.json): 0.875 / 0.625 / 0.75) exposed three agent
  bugs the scripted fake model could not, all fixed with regression tests. The one remaining miss: a fund with no
  billing household gets the generic refusal instead of the tool's reason.
- **Relevance gate:** `MIN_DENSE_SIMILARITY` calibrated to **0.43**: correct dense-only hits score 0.505–0.704, the
  best match for an out-of-corpus question 0.357.
- **End-to-end UI test** (Playwright driving Chrome against the local API, worker and Vite): a scanned PDF is rejected
  with its reason; a new PDF goes Processing → Indexed on screen without a reload and is answerable right away; three
  chat questions (fee schedule, leakage, the new upload) return cited answers; a citation chip opens the PDF on the
  cited page. UI issues found there are listed in `artifacts/product-backlog.md`.

## Local development — ledger DB core

Prerequisites: Docker running locally.

1. `./backend/scripts/db_up.sh` — idempotent: creates (or starts) a single
   Postgres 16 container named `fintech-ledger-db`, creates the `ledger_dev`
   and `ledger_test` databases if they don't already exist, and runs Alembic
   migrations against both. Safe to re-run any time — it only creates what's
   missing.
2. Copy `backend/.env.example` to `backend/.env`. It lists every deployment,
   model and tuning setting; the in-code defaults match it, so connection
   settings work out of the box against the container from step 1.
3. Run the test suite: `cd backend && $PYDEV/bin/pytest`

**Isolation level:** the balance-invariant trigger relies only on
`READ COMMITTED` (Postgres's default) — there is no read-then-conditional-write
step in this part of the system, so no stricter isolation level is set
anywhere.

## Ledger core — what the database guarantees

Every rule below is enforced by PostgreSQL itself and has a test that fails if it is removed.
The API connects as `ledger_app`, which can only `SELECT` and `INSERT`.

- **Double-entry, per currency:** a posting commits only if it has at least one debit and one
  credit and nets to zero in every currency (deferred constraint trigger on `postings` and `entries`).
- **Append-only history:** `UPDATE`/`DELETE`/`TRUNCATE` on postings, entries, schedules, valuations,
  fee calculations, AI decisions and GL exports are refused — even for the table owner. Mistakes are
  fixed by a reversal posting that must exactly mirror the original, at most once.
- **Idempotent writes:** `POST /postings` requires `Idempotency-Key`; a retry returns the original
  (`200`, `Idempotent-Replayed: true`), a reused key with a different payload is `422`, an in-flight
  duplicate is `409` with `Retry-After`.
- **Point-in-time fee rules:** schedule versions and household assignments use Postgres 18 temporal
  keys (`WITHOUT OVERLAPS`); a fee run uses the version in effect on the period end and stores the
  inputs that reproduce it exactly.
- **Governed AI:** a tool result that would move money is recorded with tool, model, prompt version and
  temperature, and posts only after a human approval — exactly the proposed entries, atomically.
- **Reproducible GL export:** a GL-ready CSV per period and cutoff, stored as a hash; regeneration
  must be byte-identical.

**Concurrency proof** (`pytest -m stress`, local, 4 workers, 50 concurrent clients):
500 requests → 400 postings for 400 keys, **0 duplicates, 0 per-currency
imbalances, 0 lost updates** on a hot account; p50 185.0 ms, p99 685.6 ms.

**Out of scope for this demo:** Aurora deployment, row-level security / multiple real tenants,
authentication, reconciliation, fee corrections, advisor compensation, event streaming.

## Running the frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://127.0.0.1:5173`.

### Extraction

The worker's `extract` stage asks the model to copy fee terms verbatim with a quote and element ids per value.
Code converts band wording to billing tiers (`app/contracts/fee_text.py`) and routes every field:
`accepted` only if the quote is found in the cited elements, all validators pass (including billing's own
`validate_tiers`), and the cited pages were parsed at grade GOOD or better — otherwise `needs_review`.
Only accepted (or human-reviewed) fields are served to the agent. The comparison tool computes the contract-vs-billing
fee gap with `fee_math.annual_fee`; a positive gap can be proposed as a correction that a human approves before it posts.
