# Fintech Ledger + Document Intelligence

A double-entry ledger core paired with a document-intelligence chat over investment advisory contracts. The model
never calculates: tools take IDs, code does the maths, and a person approves anything that would post.

Full scope: [artifacts/product-backlog.md](artifacts/product-backlog.md). What shipped, sprint by sprint:
[`CHANGELOG.md`](./CHANGELOG.md).

## Features

- **Ledger:** double-entry postings enforced by Postgres, idempotent writes, append-only history with reversals,
  household fee billing on versioned schedules, a reproducible GL export.
- **Ingestion:** local PDF parsing (Docling) and PII tokenisation (Presidio); only redacted text leaves the machine.
- **Extraction:** fee terms copied verbatim with their quote; a field is served only if its quote and validators
  check out and a second, independent reading (local OCR and a vision model on redacted crops) agrees. Anything else
  goes to a review queue.
- **Chat:** hybrid retrieval (Postgres full-text and Pinecone), a LangGraph agent whose every number is checked
  against its citations, and a contract-vs-billing fee comparison that can propose a correction for a person to approve.
- **Screens:** dashboard, review queue with an in-app PDF viewer, chat, documents, ledger with provenance.
- **Operations:** per-guest and per-IP rate limits shared in Redis, admission control that answers "busy" under
  overload, Langfuse tracing, Sentry. A public demo runs in read-only mode with per-guest overlays.
- **Tests:** 621 backend, 85 frontend.

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 / FastAPI, SQLAlchemy 2.0, Alembic |
| Frontend | React 19 + TypeScript (Vite), pdf.js |
| DB | PostgreSQL 18: `ledger_owner` migrates, `ledger_app` runs the API with `SELECT`/`INSERT` only |
| Parsing / PII | Docling + Presidio (spaCy `en_core_web_md`), local |
| Search | Postgres full-text + Pinecone serverless, merged with reciprocal rank fusion |
| LLM | OpenAI `gpt-4.1-2025-04-14` via LangChain + LangGraph; embeddings `text-embedding-3-small` |
| Shared state | Redis (rate limits) |

## Running locally

Prerequisites: Docker, and a Python 3.12 env of your choice (`$PYDEV`, its root directory).

```bash
./backend/scripts/db_up.sh                          # Postgres 18 + Redis containers, ledger_dev and ledger_test migrated
cp backend/.env.example backend/.env                # every setting, with working local defaults; set the API keys
cd backend
$PYDEV/bin/pip install -r requirements-worker.txt
$PYDEV/bin/docling-tools models download            # once, about 1 GB
$PYDEV/bin/python -m spacy download en_core_web_md  # once
$PYDEV/bin/python scripts/create_pinecone_index.py  # once
$PYDEV/bin/uvicorn app.main:app --reload            # API on :8000
$PYDEV/bin/python scripts/ingestion_worker.py       # second terminal: parse, extract, verify, index
$PYDEV/bin/pytest                                   # tests; -m stress for the concurrency proof
cd ../frontend && npm install && npm run dev        # http://127.0.0.1:5173
```

Sample documents: `scripts/prepare_samples.py --upload http://127.0.0.1:8000` loads three EDGAR agreements and a
synthetic one; `scripts/corpus_build.sh <discover> <upload>` builds the 100-document corpus. Golden set (real
OpenAI and Pinecone, about $0.50 a run): `$PYDEV/bin/pytest -m eval tests/eval -s`.

## Measured numbers

Local runs, each with its method and limit; full results in `backend/reports/`. Two questions, measured separately.

### Part 1: System performance

*Does the service stay fast, cheap and correct under load and failure?*

| Area | Result | How | Limit |
|---|---|---|---|
| Cost | $0.0093 per turn median, 3 model calls; 4.4k prompt tokens per turn (was about 24k) | Langfuse, one traced golden run | list prices |
| CPU | 41 ms per turn (was 61); peak 15.2 turns/s on 1 vCPU / 1 GB (was 10.1), 0 failed | k6 ladder, provider mock | one machine, mock latency |
| Overload | at 4x capacity, p95 7.0 s with admission control against 32.8 s without; a refused turn answers in 76 ms | k6, limit 64 turns in flight | one run each |
| Replica loss | one of 4 replicas killed: 0 hung turns, 0 timeouts, back in 11.9 s | Docker Compose, nginx | local |
| Ledger | 500 concurrent requests: 0 duplicates, 0 imbalances, 0 lost updates | `pytest -m stress`, 50 clients | local |

### Part 2: RAG pipeline evaluation

*When the chat answers, is the answer right and cited, and when it does not know, does it say so?* Rates carry a 95%
interval; the protocol is summarised after the tables.

Corpus-wide run (277 cases over all 102 documents, `gpt-4.1`, one run, judged by Claude Sonnet 5.5; 28 of 29 agree with
the API judge):

| Area | Result | Limit |
|---|---|---|
| Answer quality | 79.4% correct (72.8 to 84.8%, n=175 answerable); citations 94.8% recall (91.6 to 96.8%), 93.3% precision (89.0 to 95.9%); 17.4% over-refusal (12.6 to 23.4%): 27 of the 33 refused answerable cases had passages retrieved, 8 of them the gold passage, so the model or the citation check refuses more than the relevance threshold does | LLM-written and LLM-checked key (checker and judge are the same family); 36% of anchor reference answers differ from human labels under strict matching (upper bound 44.2%), mostly form; measured at threshold 0.50, the deployed threshold is 0.43 (see the golden set below) |
| Refusals | 80.3% of junk refused (70.0 to 87.7%, n=76): out of corpus 88.0%, underspecified 75.0%, nonsense and off topic 100%, **false premise 55.0% (34.2 to 74.2%, n=20)** | three junk categories are short of target, so their intervals are wide |
| Retrieval | gold passage reached the model for 83.4% of answerable cases (77.2 to 88.2%); 26 of 36 wrong answers were retrieval failures, 10 generation failures | 32 of 175 gold passages are outside the dense top 20 (3 are unindexed headings); `SEARCH_CANDIDATES` 20 to 50 would recover 12 of them, not yet tried |

Earlier, smaller checks:

| Area | Result | How | Limit |
|---|---|---|---|
| Golden set | at threshold 0.43: 28/28 answerable answered with a citation, 26/28 with the right numbers, 21/21 junk refused, 0% over-refusal (gate passes). At 0.44 the gate fails (2 of 27 over-refused), at 0.50 it fails (4 of 27) | 49 cases, real model, one run per threshold | curated questions on 4 documents; the gate allows no over-refusal, so one refusal on a high-scoring scoped question fails it |
| Extraction | 0 errors in 59 auto-accepted fee fields (95% upper bound 4.95%) | blind labels, LLM judge, owner-adjudicated | one corpus; LLM-judged labels |

#### Evaluation protocol in brief

Code in `backend/scripts/evalkit/`, one command per stage, each stage reading only the previous stage's file.

1. **Key.** Two Groq models (`qwen3.8-27b`, `gpt-oss-120b`) write questions, reference answers and gold passages from the
   redacted text of each document, plus out-of-corpus, false-premise, underspecified, nonsense and off-topic cases.
   Every case is checked in an isolated batch by a different model (Claude Opus 5.5; 30 early verdicts by Gemini 4
   Argon High; underspecified cases by a database query). A rejection goes to a Groq model of the other family; a case
   still disputed is dropped. 111 anchor cases built on 128 human-adjudicated contract fields measure the key's own
   error rate.
2. **Threshold.** `MIN_DENSE_SIMILARITY` is swept from 0.38 to 0.50 on retrieval scores alone (answerable passages cut
   against junk let through). The sweep alone suggested 0.50 and the final run used it; the golden gate then showed
   0.50 over-refuses 4 of 27 golden answerable cases, so the deployed threshold is 0.43, where the gate passes.
3. **Final run.** Every case goes through the deployed chat (`gpt-4.1`) once, at the threshold of that run (0.50).
4. **Judge.** Claude Sonnet 5.5 splits each answer into statements and scores correctness, citation recall and
   citation precision (ALCE); validated against the Anthropic API on a sample (28 of 29 agree).
5. **Report.** Every rate with n and a Wilson 95% interval, wrong answers split into retrieval failures (the gold
   passage never arrived) and generation failures, results split by writer.

Rules: no model grades its own family's output; prompts are frozen before the stage that uses them; each stage
checkpoints every row and resumes from the last one; every paid call is announced with its estimate first; only
redacted text leaves the machine; a checker is trusted only after negative controls (corrupted cases it must reject); the
golden set is the regression gate for any threshold or prompt change, run at the value being deployed.
To measure a change, rerun the final run and judge on the same key with a new run id and compare the metric against
its interval. Limits: the checker and the judge are the same model family, one run, three junk categories under target.

## Ledger guarantees

Each rule is enforced by PostgreSQL and has a test that fails if it is removed.

- **Double-entry, per currency:** a posting commits only if it nets to zero in every currency (deferred trigger).
- **Append-only:** updates and deletes on postings, entries, schedules, fee calculations, AI decisions and GL
  exports are refused, even for the owner; mistakes are fixed by a mirroring reversal, at most once.
- **Idempotent writes:** `POST /postings` requires `Idempotency-Key`; a retry returns the original.
- **Point-in-time fee rules:** schedules use Postgres 18 temporal keys; a fee run stores the inputs that reproduce it.
- **Governed AI:** a tool result that would move money is recorded with its model and prompt version and posts only
  after a person approves it.

## Security

Reviewed 2026-10-16 to 2026-10-18 with free tools, the AI part live against the real model (`gpt-4.1-2025-04-14`).
Full report, with each finding's tool, evidence, fix and limit:
[`docs/security/2026-10-18-security-review.md`](./docs/security/2026-10-18-security-review.md).

| Area | Checklist | What ran | Result |
|---|---|---|---|
| Application | OWASP Top 10 / ASVS | secrets in git history (gitleaks), dependencies and images (pip-audit, npm audit, Trivy), static analysis (Semgrep, Bandit), passive HTTP scan (ZAP) | 0 real secrets; 3 real High dependencies, all fixed; 0 real static findings; ZAP 0 High or Medium, 2 Low fixed and re-scanned |
| AI | OWASP Top 10 for Agentic Applications (2026) and for LLM Applications (2025) | PII egress test on every model request; live red team (Promptfoo, 138 cases, 665 turns) on goal hijack, tool misuse, privilege abuse (ASI01–03), prompt injection, sensitive data disclosure, system prompt leakage (LLM01, LLM02, LLM07) | 0 raw personal data sent; 133 of 138 passed, no case approved or posted anything; the 5 failures were 2 false positives and 3 answers showing synthetic client data the same user can already read |
| Agent design | Meta's Agents Rule of Two | code review of tools, routes and rendering | 2 pass, 1 partial (fixed: the approval card now shows the contract and the cited clauses behind the amount) |

**Agent design: Rule of Two and the lethal trifecta** (Limit, Evidence, Mitigation, Plan). An agent should hold at
most two of: untrusted input, sensitive data, and the power to change state or send data out; holding all three plus
an exfiltration channel is the lethal trifecta.

- **Limit:** the agent holds two of the three: it reads untrusted contract text and sees client data. A fooled model
  can still give a wrong answer or propose a wrong correction.
- **Evidence:**
  - Code review: 5 agent tools, 4 read-only and 1 that proposes (`compare_contract_to_billing`); 0 that fetch a URL,
    send mail, call a webhook or run code; 0 general-purpose HTTP, mail or subprocess clients imported in `backend/app` (the only outbound calls are
    the OpenAI and Pinecone SDKs, to their fixed hosts); answers render
    with 0 links or images. Rule of Two checklist: 3 checks, 2 pass, 1 partial, fixed.
  - Red team (Promptfoo, real model): 138 cases, 665 turns, 133 passed; 0 approvals, 0 postings.
  - PII egress test: every request to the model provider from indexing a contract through 2 chat turns carrying a
    name, a SIN, an email and a phone number; 0 raw values sent; shown to fail when tokenising is off.
- **Mitigation:** the third power is gated. A ledger change posts only after a person approves it on a separate
  route, seeing the computed amounts, the contract and the cited clauses; with no outbound channel the trifecta is
  incomplete, so the worst case is a wrong proposal a person rejects.
- **Plan:** a poisoned-document test (ASI06) and a kill switch (ASI10); authentication and access-control tests before
  any use outside demo mode.

**Open:** no authentication outside demo mode; not run yet: the active scan, access-control (BOLA) tests, a
poisoned-document test and a kill switch.
