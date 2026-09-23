# Document Intelligence (`feat/doc-intelligence`): design

**Date:** 2026-09-23 · **Status:** approved in brainstorming, pending written-spec review
**Backlog:** PureFacts Thursday-screen MVP → Document Intelligence MVP (re-scoped 2026-09-23)
**Research basis:** `artifacts/research/2026-09-23-document-intelligence.md` (industry research + Run 2 decisions D1–D19),
`artifacts/research/2026-09-23-agent-deployment.md` (agent serving model)

## 1. Goal

Turn investment advisory / fee agreements into **cited answers and validated fee terms**, and connect those terms to the
existing revenue book of record:

> PDF contract → parsed locally → PII tokenized → fee terms extracted with per-field routing → hybrid search →
> LangGraph agent answers with verified citations → contract terms compared with the billing schedule ("leakage")

**Success criteria**
- No raw PII value ever reaches OpenAI or Pinecone. A test proves it by spying on every prompt (§9).
- Every answer cites document · version · page · section, or refuses. Every number in an answer appears in cited
  evidence or in a tool result from the same turn (a deterministic check, §7.3).
- Each extracted field is `accepted` or `needs_review` by an explicit rule. Unreviewed `needs_review` fields are never
  served as facts.
- Record tables are append-only (the existing `forbid_mutation()` pattern). The app role can DELETE only from the
  derived search table.
- Tools take IDs, never amounts. All arithmetic runs in `billing/fee_math.py`.
- The golden set (5–8 Q&A + extraction truths) runs with `pytest -m eval` and writes a report keyed by `config_hash`.

**Delivery:** one spec, three implementation plans: **(1) ingestion** = `documents` + worker, **(2) extraction** =
`contracts`, **(3) query + citations** = `retrieval` + `assistant` + React wiring. Plan 3 depends on plan 1, not on
plan 2, except for the `get_contract_fields` / `compare_contract_to_billing` tools, which land last.

## 2. Decisions (settled; don't reopen during implementation)

| Topic | Decision |
|---|---|
| Document domain | Contracts: investment advisory agreements with tiered fee schedules. Samples from **SEC EDGAR** (exhibit (d) to Form N-1A / 485BPOS) plus **one synthetic individual-client agreement** for PII. |
| Intake format | **PDF only.** EDGAR HTML exhibits are rendered to PDF by a sample-preparation script, and that PDF is canonical, so citations always have a page. Scanned PDFs (no text layer) are rejected at upload. |
| Parsing | **Docling**, local. The raw Docling output is never stored (it contains PII and can be rebuilt from the original). |
| PII | **Presidio** analyzer + anonymizer. Deterministic tokens = HMAC(tenant key, entity type + normalised value). Values are encrypted in the app (key from the environment) in a vault table. `CA_SIN` enabled explicitly. Tokens are swapped back to values only when showing an answer to the user. |
| LLM | Hosted OpenAI via **LangChain `ChatOpenAI`**. Structured output = `.with_structured_output(Model, method="json_schema")`. Exact model snapshot pinned in config. No local model (no GPU). |
| Orchestration | **LangGraph** for the chat agent only. Ingestion and extraction are plain Python stages. No LangChain retriever or vector-store wrappers. No `interrupt()` (the DB approval path stays). Exact package versions pinned. |
| Embeddings | `text-embedding-3-small`, cosine similarity. |
| Vector store | **Pinecone**: dense only, one namespace per tenant, vector id `{version_id}#{ordinal}`. It suggests candidates; Postgres decides what's current. |
| Hybrid search | Postgres full-text search (`element_search.tsv`) + Pinecone, merged with **reciprocal rank fusion (k = 60)** in Python. |
| Record vs derived | Record tables are append-only. **Derived** = `element_search` and Pinecone. The app role gets `DELETE` on `element_search` **only** (same pattern as the column-scoped `UPDATE` grant on `accounts` in `0004`). Old versions leave the index; their records stay. Replaces the earlier "partial index `WHERE is_current`" idea, which would need UPDATEs. |
| Status | Derived from the latest `version_events` row. No mutable status columns. |
| Current version | The highest `version` per document. |
| Ingestion runtime | A **separate worker process** (`scripts/ingestion_worker.py`). The event log is the queue; each version is claimed with `pg_try_advisory_lock`. No Redis, no Celery. The API process never loads Docling or spaCy. |
| Agent runtime | **In the API process**, async LangGraph stream over **SSE** ("single host" mode). The upgrade path (worker + Postgres checkpointer + `LISTEN/NOTIFY` + cursor reconnect) is recorded in the backlog. |
| Streaming | SSE sends **progress events plus one verified `answer` event**, never unverified tokens. |
| Confidence | An explicit routing rule (§6.3), not a made-up probability. |
| Isolation level | READ COMMITTED. Uniqueness is enforced by constraints (`(document_id, version)`, `(document_id, file_sha256)`, `(version_id, ordinal)`); conflicts retry or no-op. |

## 3. Architecture

```
app/
  documents/   models dao  sniff.py (pure)  parse.py  redact.py  store.py      INGESTION
  contracts/   models dao  schema.py  fee_text.py (pure)  grounding.py (pure)   EXTRACTION
               prompts/extract_v1.md
  retrieval/   models dao  fusion.py (pure)  vector_index.py (Protocol + Pinecone + InMemory)
  assistant/   models dao  graph.py  tools.py  citations.py (pure)            QUERY + CITATIONS
               prompts/answer_v1.md
  ingestion_pipeline.py    sequences documents → retrieval → contracts ("main" wiring)
  ledger/ billing/ governance/ reporting/   unchanged
scripts/ingestion_worker.py   worker loop (also the crash-resume path)
scripts/prepare_samples.py    EDGAR HTML → PDF, writes the sample manifest
```

**Dependency direction** (no cycles; the ledger imports nothing new):
`assistant → retrieval → documents`; `assistant → contracts → documents`; `assistant → billing, governance`;
`contracts → billing` (for `Tier`, `validate_tiers`); `ingestion_pipeline → documents, retrieval, contracts`;
`routes → package entry functions` (thin, parse → call → return).

**Interfaces exist only where tests need a fake:**
- `VectorIndex`: our own Protocol with upsert, query and delete_version.
- Chat and embeddings: LangChain's `BaseChatModel` and `Embeddings` are already the interface.
- Real clients are built only in the composition roots (`main.py`, the worker entry point).

## 4. Schema (migrations `0008`–`0010`)

All record tables get the `forbid_mutation()` UPDATE/DELETE/TRUNCATE triggers. Every foreign-key column is indexed.

### 4.1 `documents` (migration `0008`, plan 1)
| Table | Columns | Constraints |
|---|---|---|
| `documents` | id, tenant_id, document_key, doc_type (`contract`), title, source_url, created_at | UNIQUE(tenant_id, document_key) |
| `document_versions` | id, document_id, version, file_sha256, mime_type, byte_size, page_count, uploaded_by, created_at | UNIQUE(document_id, version); UNIQUE(document_id, file_sha256); sha256 matches `^[0-9a-f]{64}$` |
| `version_events` | id, version_id, stage (`stored`/`parsed`/`indexed`/`extracted`/`failed`), detail jsonb, created_at | index (version_id, created_at DESC) |
| `document_elements` | id, version_id, ordinal, kind (`heading`/`paragraph`/`table`), section_path text[], page_start, page_end, text_redacted, parser_version | UNIQUE(version_id, ordinal); page_start ≤ page_end |
| `pii_tokens` | tenant_id, token, entity_type, value_encrypted bytea, created_at | PK(tenant_id, token); insert ON CONFLICT DO NOTHING |

The original file is stored on disk: `DOCUMENT_STORE_DIR/originals/<sha[0:2]>/<sha>`.
`render_markdown(version_id)` builds the markdown view from `document_elements` in order. It is not stored.
Page-level Docling grades are kept in the `parsed` event's `detail`
(`{"pages": {"1": {"grade": "GOOD", "score": 0.83}, …}}`).

### 4.2 `contracts` (migration `0009`, plan 2)
| Table | Columns | Constraints |
|---|---|---|
| `extraction_runs` | id, version_id, schema_version, model_id, prompt_version, temperature, config_hash, input_hash, raw_output jsonb, created_at | hashes are 64 hex chars |
| `extracted_fields` | run_id, field_path, value jsonb, element_ids uuid[], quote, grounded, validator_errors text[], page_grade, routing (`accepted`/`needs_review`) | PK(run_id, field_path) |
| `field_reviews` *(schema now, UI after Thursday)* | run_id, field_path, decision (`confirmed`/`corrected`/`rejected`), corrected_value jsonb, decided_by, reason, decided_at | PK(run_id, field_path); FK → extracted_fields |

### 4.3 `retrieval` + `assistant` (migration `0010`, plan 3)
| Table | Columns | Notes |
|---|---|---|
| `element_search` | element_id PK, tenant_id, document_id, version_id, tsv tsvector | **Derived.** GIN(tsv); index (tenant_id, document_id). No append-only trigger; `GRANT DELETE ON element_search TO ledger_app`. |
| `chat_turns` | id, tenant_id, session_id, question_redacted, answer_redacted, citations jsonb, retrieved jsonb, outcome (`answered`/`refused`/`timed_out`/`cancelled`/`error`), model_id, prompt_version, graph_version, input_tokens, output_tokens, latency_ms, created_at | Append-only; index (tenant_id, created_at DESC), (session_id, created_at) |

`tool_invocations` (existing) receives every tool call with `turn_id` inside `input`.

## 5. Ingestion (plan 1)

### 5.1 Upload: synchronous and fast (`POST /documents`)
1. Size ≤ `MAX_UPLOAD_BYTES` (20 MB). Magic bytes = PDF. Not encrypted. `pypdf` gives the page count and confirms a text layer.
   Any failure → **422** problem+json, nothing stored.
2. SHA-256. If `(document_id, sha)` already exists → **200** with the existing version (no-op).
3. Write the file to the store, then insert `document_versions` (next version; a unique conflict retries once) and a
   `stored` event, in one transaction → **202** `{version_id, status_url}`.

### 5.2 Worker (`scripts/ingestion_worker.py`)
The loop runs every `POLL_SECONDS`. It finds versions whose latest event isn't finished, claims each with
`pg_try_advisory_lock(hash(version_id))` and runs the next stage. **One pipeline at a time** (`# ponytail: single
worker; more workers are safe because of the advisory lock, add when volume needs it`).

| Stage | Owner | Writes (one transaction, including its event) |
|---|---|---|
| `parse_redact` | documents | Docling → elements (kind, section_path, pages) → Presidio → `document_elements` + `pii_tokens` + `parsed` event (with page grades) |
| `index` | retrieval | embed (breadcrumb + text) → Pinecone upsert (fixed IDs) → INSERT `element_search` for the new version + DELETE rows of older versions → `indexed`; after commit, delete old-version vectors (best effort) |
| `extract` | contracts | §6 → `extraction_runs` + `extracted_fields` + `extracted` |

Search indexing runs before extraction, and the two are independent.
Models (Docling ≈ 1 GB, spaCy `en_core_web_lg` ≈ 800 MB) load once per worker process.

### 5.3 Failures
| Failure | Behaviour |
|---|---|
| OpenAI / Pinecone | Timeouts: structured output **60 s**, embeddings **15 s**, Pinecone **10 s**. **3 retries** with exponential backoff and jitter, only on timeouts, 429 and 5xx. Then a `failed` event `{stage, error_type}`. |
| Crash midway through a stage | The transaction rolls back. The next loop reruns the stage. |
| Crash after the Pinecone upsert, before commit | Rerun overwrites the same vector IDs. |
| Deleting old vectors fails | Harmless: search results are checked against `element_search`. |
| A stage runs twice | `document_elements` UNIQUE → already done. A second extraction run is a new run; the latest wins. |

### 5.4 Endpoints
`POST /documents` · `GET /documents` (current version and its status) · `GET /documents/{id}` (versions + events) ·
`GET /documents/{id}/versions/{v}/file` (original PDF. It contains PII: it sits behind the demo-user dependency, with a
`ponytail:` note that real authorization comes with authentication).

## 6. Extraction (plan 2)

### 6.1 Schema: `ContractTerms`
Every field is `Cited[T] = {value: T | null, quote: str, element_ids: [str]}`. `null` means "not stated".

`adviser`, `client` (token strings) · `agreement_date`, `effective_date` · `fee_basis` · `fee_method`
(`graduated`/`cliff`, the billing enum) · `fee_tiers: [{band_text, rate_text}]`, copied **word for word** ·
`billing_frequency` (monthly/quarterly) · `payment_timing` (arrears/advance) · `termination_notice_days` ·
`governing_law` · `signatories: [{name token, title}]` · currency (USD for EDGAR samples).

### 6.2 The call
- Input: `render_markdown` of the current version, each element wrapped as
  `<element id="E12" page="3" section="4 › Compensation">…</element>` inside `<document>`. The system prompt treats
  the document as data (defence in depth only).
- The whole document goes in one call (EDGAR advisory agreements are about 10–20 pages). Splitting and merging is
  deferred past about 100 pages.
- `temperature=0`, `timeout=60`, `max_retries=3`. If the output doesn't validate against the schema: retry once with the
  validation error sent back, then `failed`.
- `prompt_version` = hash of `prompts/extract_v1.md`. `config_hash` = hash(model snapshot, prompt hash,
  schema_version, docling version, presidio version). `input_hash` = hash of the rendered input.

### 6.3 Routing: code decides
- `fee_text.py` turns `band_text` + `rate_text` into `fee_math.Tier` (the running total for "next …" bands is computed
  in code).
- **Grounded:** the normalised quote appears in the cited elements' text **and** the literal value (`rate_text`, the date
  string, the token) appears in the quote.
- **Validators:** `fee_math.validate_tiers()` (reused); `0 < rate_bps ≤ MAX_ANNUAL_RATE_BPS (300)`;
  `0 ≤ notice_days ≤ MAX_NOTICE_DAYS (365)`; adviser ≠ client; dates parse; a required field that is null → error.
- **Page grade:** the lowest Docling grade over the cited pages.
- **Rule:** `accepted ⇔ grounded ∧ no validator errors ∧ page grade ≥ GOOD`; otherwise `needs_review`.
  The inputs are stored per field.

### 6.4 Served fields
`served_fields(document_id)` = the latest run on the current version. Per field: a `corrected` review value, otherwise
an `accepted` value. `needs_review` without a review and `rejected` fields are excluded, and their absence is visible
to callers.

### 6.5 `compare_contract_to_billing(document_id, household_id, as_of)`
1. Takes the served tiers and method. If any tier field isn't served, it **refuses** and names the fields.
2. Loads the household's schedule version in effect on `as_of` (billing).
3. Returns the tier-by-tier differences, plus the **annual fee gap** at the household's current value: `annual_fee()`
   under both schedules, in minor units.
4. Records a `tool_invocations` row (result amount + currency + citations). **Stretch:** if the gap is non-zero,
   `proposed_entries` makes the invocation critical, so it goes through the existing human-approval path.

## 7. Query + citations (plan 3)

### 7.1 Search: `retrieval.search(query, tenant_id, document_ids=None, k=8)`
1. Tokenise PII in the query (same HMAC).
2. Full-text: `websearch_to_tsquery('english', q)`, `ts_rank_cd`, top 20.
3. Vector: embed → Pinecone top 20 (tenant namespace, optional document filter).
4. Drop vector hits whose element isn't in `element_search`.
5. Reciprocal rank fusion (k = 60) → top k.
6. Parent expansion: each hit gets its section's elements (same version, same `section_path` prefix), capped at
   `MAX_SECTION_TOKENS`.
7. Relevance gate: no full-text match **and** best cosine < `MIN_DENSE_SIMILARITY` → empty result (the threshold is
   calibrated on the golden set).

It returns `Evidence{element_id, document_id, title, version, page_start, page_end, section_path, text, context}`.

### 7.2 Graph
```
route ──► agent ⇄ tools ──► answer ──► verify ──ok──► respond
                                         └─fail─► answer (1 retry) ──fail──► refuse
```
- `route`: a deterministic keyword check for calculation questions → forced `tool_choice` =
  `compare_contract_to_billing`.
- `tools`: `list_documents` · `search_contracts` · `get_contract_fields` · `compare_contract_to_billing`. Every call is
  logged through `governance.record_invocation()` with `turn_id`. The evidence each call returns is added to the turn
  state.
- `answer`: structured output `Answer{text, citations: [element_id | invocation_id], refused}`.
- Limits: `recursion_limit=8`; the whole turn runs under `asyncio.timeout(60)` → refusal + `timed_out`. 30 s per model
  call.
- Memory: the last `HISTORY_TURNS` turns of the session, from `chat_turns`.

### 7.3 Verification (`citations.py`, pure)
- Every cited ID is in this turn's evidence or tool results.
- Every number in the text (currency, percent, integer, date parts; normalised) appears in a cited element's text or in
  a cited tool result.
- At least one citation, unless the answer is a refusal.

### 7.4 Endpoint and SSE
`POST /chat {session_id, message}` → `text/event-stream`: `progress` (`searching`, `reading_fields`, `comparing`),
then exactly one of `answer {text, citations[]}` / `refused {reason}` / `error`. A citation is
`{document_title, version, page, section, quote, file_url}`, where `file_url` ends in `#page=N`. For a computed figure,
the citation is `{tool, invocation_id, inputs_cited[]}`. A client disconnect cancels the turn → `cancelled`.

### 7.5 Frontend
Wire the existing chat and documents screens: upload, status, chat over SSE (fetch + ReadableStream; no new npm
package), and citation chips → the PDF at a page plus the quote highlighted in the markdown panel.

## 8. Security and privacy
- Raw PII exists only in the original file store and in encrypted vault values. Everything sent to the model is redacted.
- Tool arguments are IDs only. The model has no write tool. Ledger writes need human approval (existing).
- The PII HMAC key and vault encryption key come from the environment and are never committed.
  `.env.example` lists them with placeholder values.
- The original PDF endpoint and detokenisation sit behind the single demo-user dependency until authentication exists.

## 9. Testing (write the failing test first)
| Layer | Scope |
|---|---|
| Pure unit | `sniff`, `fee_text` (real EDGAR wording), `grounding`, `fusion`, `citations`, HMAC determinism, `render_markdown` |
| Postgres | migration up→down→up; triggers reject UPDATE/DELETE on new record tables; `ledger_app` DELETE works only on `element_search`; current version; stage idempotency; `element_search` swap; routing; served fields; compare tool vs `build_fee_scenario()` with a hand-computed gap |
| `slow` | Docling + Presidio on one committed synthetic 2-page PDF: pages and sections present, name and SIN tokenised, no raw PII in `document_elements` |
| Agent (fakes) | `GenericFakeChatModel` (a subclass with pass-through `bind_tools`), `DeterministicFakeEmbedding`, in-memory `VectorIndex`: forced routing; uncited number → retry → refuse; invocation rows written; timeout; stale-vector drop; relevance-gate refusal |
| SSE | progress events, then exactly one answer/refused, with the citation shape |
| Privacy | A spy chat model captures every prompt across ingest → extract → chat on the PII fixture; asserts no raw PII value appears |
| `eval` (manual, real APIs) | `tests/eval/golden.yaml` (5–8 cases: fact, calculation, interpretive, mixed, should-refuse) + extraction truths per sample → `reports/eval-<config_hash>.json`; calibrates `MIN_DENSE_SIMILARITY` |

`pytest.ini`: `addopts = -m "not stress and not eval"`; register the `slow` and `eval` markers.

## 10. Infrastructure changes
- `requirements.txt`: `docling`, `pypdf`, `presidio-analyzer`, `presidio-anonymizer`, `langchain-openai`,
  `langchain-core`, `langgraph`, `pinecone`, `cryptography`, all pinned to exact versions.
  `sse-starlette` only if FastAPI's `StreamingResponse` proves insufficient.
- One-time model downloads are documented in the README (`docling-tools models download`,
  `python -m spacy download en_core_web_lg`).
- `.env.example`: `OPENAI_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX`, `DOCUMENT_STORE_DIR`, `PII_HMAC_KEY`,
  `PII_VAULT_KEY`, `CHAT_MODEL`, `EXTRACTION_MODEL`.
- `CLAUDE.md` stack table updated in the same sprint: Textract → Docling + Presidio; pgvector → Pinecone + Postgres
  full-text search; LiteLLM → LangChain/LangGraph over OpenAI.

## 11. Build order
**Thursday slice:** plan 1 → plan 3 search and chat over `search_contracts` → plan 2 → the two field tools → frontend
wiring → golden set. **After Thursday (specified here, not built):** versioning UI/flows beyond the schema (the schema
and `element_search` swap are built), the stronger-model re-extraction cascade, the CI eval gate, the review UI, and the
agent-serving upgrade path.

## 12. Out of scope (explicit, with revisit triggers in the research file)
Scanned PDFs / OCR · Presidio image redactor · highlighting the exact spot on the PDF · HTML/DOCX intake · automatic
document classification · local LLM · dual-LLM / CaMeL · Pinecone single-index hybrid · partitioning current/archived
versions · Temporal durable execution · WebSocket transport · LangGraph `interrupt()` · S3 storage/retention ·
`rule_versions` · adversarial ingestion categories · full 15–20 golden set · real authentication/authorization.
