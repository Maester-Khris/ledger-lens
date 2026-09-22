# Product Backlog — Fintech Ledger + Document Intelligence

Companion to `2026-08-29-fintech-ledger-poc-sprint.md` (the scope-definition
doc — read that first for the *why* behind every line here). This file is
the *what, in order*, sized to be executed without re-litigating scope
mid-sprint. If something feels missing while building, check the Icebox
section at the bottom before adding it — it's very likely already been
considered and deliberately cut.

**Repo:** new, separate from `rx-next`. One repo, one language, two phases
as modules (`ledger/`, `documents/`), not two services.

**Execution order (2026-08-30, supersedes the plain Sprint 1/Sprint 2 day
framing below): Week 1 (MVP) → Week 2 (Next Iteration) → Iteration 3
(Document Intelligence Chat).** Reverse-engineered from 6 real, current
fintech/payments job postings (Chexy, Stripe, Loop Financial, Float,
Wagepoint, Interac — gathered 2026-08-30) rather than worked in file order.
Weeks 1 and 2 are both built entirely from the ledger core (formerly "Sprint
1") plus a small number of genuinely new additions justified by direct JD
evidence — the Document Intelligence Chat work (formerly "Sprint 2") is real
and still gets built, but it maps to only one of six postings (Wagepoint,
which is stack-mismatched anyway) and is deliberately pushed to Iteration 3
rather than Week 1, because a complete hardened ledger outsignals a half-built
second system. See "Why this order" below each section for the JD evidence
behind each call.

Sprint 1/ledger content below stays a **PoC** — proves invariants, no UI,
never demoed live. The Document Intelligence Chat work stays an **MVP** — a
real, usable product with a UI. That distinction is unchanged by the
reordering, only the scheduling is.

**Full stack (locked):**

| Layer | Choice |
|---|---|
| Language/framework | Python 3.11 + FastAPI (both phases, one service) |
| DB | PostgreSQL — localhost for dev, Amazon Aurora PostgreSQL for the demo/deploy run |
| Vector store | **pgvector**, same Postgres instance — core scope, Sprint 2's product is retrieval-based by definition |
| OCR | AWS Textract, **synchronous API** (AnalyzeDocument — not the async job API) — single/few-page tax slips fit the sync size limits, so there is no job to poll and no completion event to notify on. No API Gateway, no webhook, no SNS/SQS. |
| LLM gateway | **LiteLLM** — core scope. The chat endpoint's generation call goes through it rather than a hand-rolled provider abstraction, deliberately different from MediCoord's own hand-built Groq/Anthropic abstraction so this reads as a second, non-redundant skill (a production gateway with built-in retry/cost-tracking) instead of the same trick twice. |
| Chat UI | React (minimal — Vite scaffold, no framework beyond React itself) against the FastAPI backend. Next.js is a deliberate later-expansion option if this ever needs SSR/routing/deployment features React alone doesn't give — not part of this build. Visible and usable is the bar, not polished. |
| Migrations | Alembic (SQLAlchemy) or a small hand-rolled sequential-SQL runner — pick one on Day 1, don't evaluate both |
| Testing | pytest; concurrency stress test via `asyncio` + `httpx.AsyncClient` (no need for a separate load-testing tool at this scale) |
| Transport between phases | none — Phase 2 imports and calls Phase 1's posting logic in-process. No gRPC, no internal API. |
| Transport security | **HTTPS/TLS only, everywhere this is deployed, no exception for the demo.** Table stakes for a fintech-facing surface — applies to the ledger API, the chat API, and the React UI alike. |

---

## PureFacts alignment + Thursday screen MVP (added 2026-09-22)

**Hard deadline: PureFacts recruiter screen, Thu 2026-09-24.** Both halves of
this project (Ledger, Document Intelligence) need a real, running v1 by then
— something to point at in both fintech vocabulary ("Revenue Book of Record,"
"auditable AI decision") and technical-seniority vocabulary (idempotency,
citation-grounded retrieval, tool-call provenance) on the same call. This
section is the cut-down, JD-aligned scope that actually ships by Thursday.
It supersedes the Week 1/Week 2/Iteration 3 pacing below for scheduling
purposes only — those sections stay as the fuller reference plan and the
source for anything marked **deferred** here.

**Current real state (verified 2026-09-22):** Epics 1.1 (schema/migrations)
and 1.2 (balance-invariant deferred trigger) are done, with DAO + tests.
`POST /postings` (1.3) is not built. Zero Document Intelligence code exists
yet. The frontend already has static chat/documents/ledger screens scaffolded
(commit `e03f653`) — wire real endpoints into these rather than building new
UI, that's most of the UI cost already paid.

### Stack deltas for this MVP (vs. the locked table above)

| Layer | Original plan | Thursday MVP | Why the change |
|---|---|---|---|
| OCR/extraction | AWS Textract (sync `AnalyzeDocument`) | **LlamaParse** (vision-LLM parsing) | No AWS IAM/boto3 setup to debug against a deadline; handles multi-page natively (Textract's single-page sync limit was a named risk in Epic 2.1); matches your stated direction. **Trade-off, stated honestly**: no per-region confidence score the way Textract gives one — confidence-filtering (Epic 2.2) is deferred, not silently dropped. |
| Vector store | pgvector (same Postgres instance) | **Pinecone** | Literal match to the JD's named stack (Pinecone/Weaviate) — worth having the real vendor name to say on the call. **Trade-off, stated honestly**: gives up pgvector's same-instance transactional consistency (the same reasoning that rejected the S3-ARN rule-governance design in the Icebox applies here in miniature) — a real, conscious trade for a 2-day demo, not an oversight, and worth naming if asked why. |
| LLM integration | LiteLLM gateway | **Raw OpenAI SDK** | JD reads as wanting literal OpenAI SDK hands-on time, not a gateway abstraction. Confirmed with you: framework choice (LangChain/LlamaIndex/LangGraph) was never actually a screen blocker either way — so simplifying to the raw SDK is strictly less to build, not a downgrade. |
| Embedding model | (unnamed) | **OpenAI `text-embedding-3-small`**, pinned in the migration | Same vendor as generation — one API key, one bill, one less integration to debug this week. |

Everything else in the locked stack table (Postgres, FastAPI, Alembic, pytest,
in-process transport, HTTPS/TLS) is unchanged.

### Ledger MVP — must land by Thursday

- [ ] `POST /postings` (Epic 1.3 as written) — idempotency key, payload-hash
      409 on divergent retry. This is the one missing piece between "schema
      exists" and "there's an API to demo."
- [ ] Concurrency proof, **trimmed** Epic 1.4: `asyncio.gather` + `httpx.AsyncClient`,
      a few hundred requests mixing new postings, exact-duplicate retries, and
      a hot-account scenario. Capture real N / duplicate count / imbalance
      count / p99 latency. Skip the deep bottleneck-mechanism profiling and
      the Aurora re-run — local numbers are enough for Thursday, real numbers
      beat rounded ones regardless of scale.
- [ ] Compensating reversal (Epic 1.7 as written) — stretch, only after the
      two items above are solid. Cheap (reuses existing schema/idempotency),
      but not the thing that sinks the call if cut.
- [ ] One short README section: the one invariant proven, the real captured
      numbers, an explicit "Out of scope for this demo" line (Aurora, event
      streaming, reconciliation — point at Week 2 below as the stated roadmap).

**Deferred, mention only as roadmap on the call:** Aurora deployment (Epic
1.5), correlation-ID logging + CI gate (Epic 1.8), and all of Week 2
(transactional outbox, reconciliation matcher, observability, fault
injection) below — unchanged, still real, just not needed to demo Thursday.

### Document Intelligence MVP — must land by Thursday

- [ ] Ingest 3–5 real sample tax-style documents (mix of clean + messy,
      at least one genuinely multi-page — LlamaParse removes the single-page
      constraint that gated the sample set under Textract) through LlamaParse
      → markdown output.
- [ ] Chunk by LlamaParse's own markdown structure (headers, tables) — no
      custom Textract-LAYOUT chunker to build; this is most of the time
      Epic 2.2 originally budgeted, saved by the OCR swap.
- [ ] Embed chunks with `text-embedding-3-small`, index into Pinecone,
      storing document id / page / section per chunk (citation depends on this).
- [ ] Chat endpoint: top-k retrieval → OpenAI chat completion. Every answer
      cites document/page/section — no answer without a citation. Explicit
      "I don't know" fallback when nothing clears the relevance threshold —
      same fail-safe-over-fabrication rule as MediCoord.
- [ ] Wire the existing static chat/documents React screens to this endpoint
      — real demo traffic through the real UI, not a new screen to build.
- [ ] **One deterministic tool**, a single computed figure (e.g. total
      reported income) as a pure Python function. Signature takes
      `document_id` only, never a model-asserted amount — the concrete,
      literal answer to "how is AI governed here."
- [ ] **`tool_invocations` table** — append-only: id, session_id, tool_name,
      document_id, result, created_at. This is the artifact for "log every
      AI decision" — the single most direct answer to PureFacts' "AI must be
      practical, governed, and auditable" line, and it's cheap (one table,
      one insert per call).
- [ ] 5–8 manually-verified sanity Q&A pairs as a mini golden set — enough to
      say "evaluated," not the full 15–20-question set.

**Stretch, only attempt once everything above works:** post the tool's
validated figure back into the ledger via the existing `POST /postings`,
idempotency key = `(document_id, tool_invocation_id)`. This is the single
highest-value demo beat if reached — it's the literal Revenue-Book-of-Record
story, an AI-derived figure that can't land in the ledger except through the
same audited, idempotent path every other posting uses. Build it last, cut it
first if short on time; the chat + citations + tool_invocations trio above is
already a complete, honest story without it.

**Deferred, mention only as roadmap or honest known-gap on the call:** S3
storage/retention policy (local disk for now, documented as the next step),
Textract-style confidence filtering (LlamaParse doesn't expose per-region
confidence the same way — state this as a known, named gap, not a miss),
`rule_versions` governance table, the dual-LLM prompt-injection defense,
max-iteration/token-budget caps, the three adversarial ingestion test
categories, the full 15–20 golden-set eval, and adopting LangChain/
LlamaIndex/LangGraph (confirmed not required for this screen).

---

## Week 1 — MVP: Ledger Core, hardened (Days 1–5, hard cap)

**Why this order:** double-entry ledger, idempotency, and transaction/audit
integrity are the recurring, required themes across the well-matched
postings (Chexy names ledgers/double-entry/idempotency/reconciliation
verbatim; Float names transactional integrity; Loop names audit trails).
Epics 1.1–1.4 already cover the first three fully. Days 4–5 close the
remaining gap between "proven correct" and "demonstrably production-minded"
without adding new infrastructure — everything below reuses what Epics
1.1–1.5 already built.

### Epic 1.1 — Schema & migrations (Day 1 morning)
- [ ] `accounts` table: id, name, currency, created_at
- [ ] `postings` table: id, idempotency_key (UNIQUE), description, created_at — no updated_at, no update path at all
- [ ] `entries` table: id, posting_id (FK), account_id (FK), direction (enum: `debit`|`credit`), amount (integer, minor units), created_at
- [ ] Migration tool decided and wired (Alembic recommended — matches FastAPI/SQLAlchemy conventions, avoids hand-rolling migration tracking)

### Epic 1.2 — Balance invariant enforcement (Day 1 afternoon)
- [ ] Application-level check: within the same DB transaction as the insert, sum(debit entries) must equal sum(credit entries) for the posting being created, or the transaction rolls back
- [ ] **Must be a real `CREATE CONSTRAINT TRIGGER ... INITIALLY DEFERRED`, not a plain `AFTER INSERT` trigger.** A plain trigger fires per-row, immediately — it will reject a posting after its first entry lands but before its balancing entry is inserted in the same transaction. This is a one-line DDL mistake that ships a broken invariant while unit tests (which likely insert all rows in one statement) pass anyway. Verify in code review, not by trusting the ticket description.
- [ ] **State the isolation level explicitly, in code and in the README: `READ COMMITTED` is correct and sufficient here** — there is no read-then-conditional-write step (no balance-check gating the insert). If a future feature adds an overdraft/limit check that reads current balance before allowing a posting, that decision reverses immediately and needs re-opening then, not assumed away now.
- [ ] Atomic write pattern: insert-with-`ON CONFLICT DO NOTHING RETURNING id` on `postings`, entries inserted only if a row came back — via one atomic CTE (`WITH ins AS (INSERT INTO postings ... RETURNING id) INSERT INTO entries SELECT ... FROM ins`), not two separate round-trips gated by an app-level `if`. Two round-trips reopens the exact race the UNIQUE constraint was supposed to close.
- [ ] Unit tests: balanced posting succeeds, unbalanced posting is rejected, rejection leaves zero partial rows

### Epic 1.3 — Idempotent posting endpoint (Day 2 morning)
- [ ] `POST /postings` — accepts `{ idempotency_key, entries: [{account_id, direction, amount}] }`
- [ ] Request validation (entries non-empty, amounts positive integers, valid account references)
- [ ] Idempotency handling: duplicate `idempotency_key` returns the original posting, does not attempt a second insert — implemented via the UNIQUE constraint + conflict handling, not a check-then-insert race
- [ ] **Payload-hash check on key reuse**: store a hash of the request body alongside the idempotency key at first insert. If the same key arrives again with a *different* payload (client bug, corrected-amount retry, replay), return 409, not the silently-cached original posting — a silent mismatch here is exactly the kind of bug that surfaces as "why doesn't the customer's statement match what we sent" months later.
- [ ] Unit tests: duplicate key (sequential) returns same posting; new key creates new posting; duplicate key with a different payload returns 409

### Epic 1.4 — Concurrency + idempotency stress test (Day 2 afternoon)
- [ ] Test harness: fire N concurrent requests at `POST /postings` via `asyncio.gather` + `httpx.AsyncClient`, mixing genuinely-new postings with exact duplicate retries of already-sent idempotency keys
- [ ] **Include a hot-account scenario explicitly**: many concurrent postings targeting the *same* account, not just N independent accounts. Every entry insert takes a `FOR KEY SHARE` lock on its parent account row to protect the FK — this is the textbook ledger contention point, and a test using only independent accounts will never trigger it, producing a falsely optimistic "scales linearly" read.
- [ ] Assertion 1: distinct postings created == unique idempotency keys sent
- [ ] Assertion 2: every account's derived balance (sum credits − sum debits from `entries`) matches the independently pre-computed expected value
- [ ] Assertion 3: zero postings exist anywhere with debits ≠ credits
- [ ] Run it for real, capture the actual numbers (request count, duplicate count, imbalance count, p99 latency) — these numbers go in the README verbatim, not rounded or estimated
- [ ] **Identify the actual bottleneck mechanism as concurrency scales** — connection pool exhaustion, row-lock contention on a hot account, or the deferred trigger's own overhead — by profiling the run, not asserting one. "It just worked" is not an acceptable answer here; this is the first thing a technical interviewer will probe on the stress test, and a placeholder answer reads as an unverified claim, not evidence.

### Epic 1.5 — Aurora deployment (Day 3 morning)
- [ ] Provision a minimal Aurora PostgreSQL instance (Serverless v2, smallest capacity — this is a demo run, not a standing service)
- [ ] **Pin a fixed min/max ACU floor for the benchmark window** and state it next to the captured numbers in the README. Aurora Serverless v2's `max_connections` scales with current ACU — an unpinned benchmark risks a mid-test scaling event, which would make the p99 numbers measure Aurora's autoscaling latency instead of the code's behavior.
- [ ] Confirm the app's DB connection pool `max_size` fits under Aurora's connection ceiling at the pinned ACU tier — otherwise a "connection pool exhaustion" finding from Epic 1.4 could be a pool-config artifact, not a real architectural result.
- [ ] Point the service at Aurora via connection string only — confirm zero code changes needed (this is the point of choosing Aurora)
- [ ] Re-run the Epic 1.4 stress test against Aurora, capture those numbers separately from the local run
- [ ] Tear down or pause the Aurora instance after capturing results — cost control, this is a portfolio artifact, not a running service

### Epic 1.6 — README (Day 3 afternoon)
- [ ] States the one invariant proven, in one sentence
- [ ] Real captured numbers from both the local and Aurora stress-test runs
- [ ] **State the Aurora motivation transparently**: closing a named gap from two real prior rejections, not a scale requirement this project has. Say this outright rather than let a reader infer resume-driven development.
- [ ] Explicit "Out of scope" section (see Icebox below) — named, not silently absent
- [ ] Stop. Do not start Days 4-5 in the same sitting if it can be avoided — evaluate the numbers first.

### Epic 1.7 — Compensating-reversal posting (Day 4 morning)
- [ ] `reverses_posting_id` nullable FK on `postings`; reversing a posting never mutates it, it inserts a new posting with swapped debit/credit entries referencing the original. Reuses the existing schema, invariant, and idempotency mechanism entirely — no new infrastructure.
- [ ] This is the cheap, correctly-scoped version of the pending/settled-funds/audit-trail signal from the research; a full saga orchestrator is explicitly *not* this ticket (see Icebox — held, not reversed, even against Loop's Temporal.io mention).
- [ ] **Decide reversal-of-a-reversal explicitly, don't let it fall out of the schema by accident.** `reverses_posting_id` is not restricted to pointing only at non-reversal postings, so a reversal can itself be reversed by default — this is the deliberate choice: restricting it would need a `posting_type` check with no stated business justification for the restriction. State this as a decision in the README, not an untested edge case.
- [ ] Unit test: reversing a posting produces a new, correctly-inverted posting; original is untouched; net balance across both equals zero. **Second test: reverse a reversal** (a chain of two), assert the net balance across all three postings is still zero and the chain is traceable via `reverses_posting_id`.

### Epic 1.8 — Correlation-ID logging + CI gate (Day 4 afternoon – Day 5)
- [ ] Pulled forward from "Technical battle-test findings." Structured logging on every write path with a request-to-DB-row correlation ID — trace a posting back to the request that created it without relying on `created_at` timestamp matching.
- [ ] A CI pipeline (even minimal — GitHub Actions running pytest) gating Epics 1.1–1.7's test suite on every change. Doesn't need Textract/LiteLLM mocking yet since nothing in Week 1 calls either.
- [ ] **Standing rule for every migration from here forward, including Week 2 and Iteration 3's**: an up/down migration test in the same CI gate — apply, verify schema, roll back, verify clean. Not a one-off ticket, a policy this gate enforces going forward.
- [ ] Both give the "audit trail" and "transaction integrity" claims something demonstrable behind them before this is shown to anyone, at low cost.

**What's deliberately cut from Week 1: all of the Document Intelligence Chat
work (Iteration 3, below).** Two reasons: it maps to only one of six real
postings (Wagepoint, and that one's stack-mismatched anyway), and a partial
2-day slice of it (ingestion + half of chunking, no chat endpoint, no UI, no
tool-calling) would repeat Iteration 3's own documented failure mode — a RAG
pipeline with no visible product. A complete, hardened ledger with real
stress numbers outsignals a half-started second system.

**Resume bullets for Week 1 (grounded only in what actually ships — fill
`[N]`/`[X]` placeholders with the real stress-test output, never invented or
rounded numbers):**

1. *"Built a double-entry ledger on PostgreSQL enforcing debit/credit balance invariants via a deferred constraint trigger and application-level transactional checks; proved correctness under concurrent load — `[N]` concurrent postings including deliberate duplicate retries and hot-account contention, 0 balance violations, 0 duplicate writes, p99 `[X]`ms — deployed on Amazon Aurora PostgreSQL."*
2. *"Implemented an idempotent payment-posting API using unique-constraint-enforced idempotency keys with payload-hash mismatch detection (409 on divergent retry), closing the duplicate-write race that check-then-insert idempotency leaves open — validated with an automated concurrency stress harness."*
3. *"Designed an audit-safe compensating-reversal pattern for correcting ledger entries — reversals never mutate the original posting, preserving a fully immutable transaction history — built on the same idempotency and balance-invariant guarantees proven under concurrent load."*

None of these claim event-driven architecture, reconciliation, or NestJS/Node
— those aren't in Week 1's scope. Using that vocabulary before it's actually
built is the same fabrication risk flagged everywhere else in this doc.

---

## Week 2 — Next Iteration (Days 6–10)

**Why this order:** prioritized by which addition closes the biggest verified
gap against the real JDs, not file order. Event-driven architecture (Kafka/
Pub-Sub) is named as *required* at both Chexy and Loop and is currently 0%
covered anywhere in this project — highest priority by a clear margin.
Reconciliation is named verbatim at Chexy. The other two items were already
sitting in "Technical battle-test findings," pulled forward here because they
directly evidence Float's and Loop's "distributed systems" language cheaply,
on infrastructure Week 1 already built.

### Epic 2.1 — Transactional outbox + event stream (Days 6–7, NEW scope)
- [ ] A `posting_events` row written in the *same transaction* as each posting insert — this avoids the dual-write problem (writing to the DB and publishing an event as two separate, non-atomic steps), itself a real senior-level signal independent of the messaging tech chosen.
- [ ] Publish to a real broker — Kafka or Redpanda via docker-compose, whichever is faster to stand up credibly.
- [ ] One downstream consumer proving the event actually flows end-to-end (even a trivial one — log the event, or update a read-model row).
- [ ] README note: this is a transactional-outbox pattern, named as such, not "we added Kafka" — the pattern is the signal, the specific broker is a swappable detail.

### Epic 2.2 — Minimal reconciliation matcher (Day 8, NEW scope, partial Icebox reversal)
- [ ] Ingest one flat CSV standing in for an external settlement file (a small fixture, not a live integration).
- [ ] Match CSV rows to existing postings by a stored reference field.
- [ ] Classify each row: matched, unmatched (in the ledger, not in the file, or vice versa), or mismatched (present in both but amounts disagree).
- [ ] Expose a report endpoint or a generated report file — no new source-of-truth ambiguity, no live second system. **This reverses the Icebox's original reconciliation rejection, which assumed a full external-system integration; the minimal matcher version doesn't have that cost and closes Chexy's named requirement directly.** The full external-integration version stays correctly rejected.

### Epic 2.3 — Observability baseline (Day 9, pulled forward)
- [ ] An alert distinguishing an invariant-violation rollback (Epic 1.2's constraint trigger firing) from an ordinary validation error — a ledger where these look identical in the logs isn't operable.
- [ ] A health/readiness endpoint that detects a broken connection pool after an Aurora failover/scaling event and reconnects, rather than requiring a manual restart.

### Epic 2.4 — Light fault injection (Day 10, pulled forward)
- [ ] A dropped DB connection mid-transaction; a simulated connection-pool exhaustion event. Assert the balance invariant still holds and no partial postings survive either scenario.
- [ ] Directly evidences Loop's "distributed systems fault tolerance" line, cheaply, on infrastructure that already exists by this point.

**Temporal.io is deliberately absent from both weeks.** Loop names it
specifically, but running it credibly (dev server, worker process, workflow/
activity definitions, retry/signal semantics) is a multi-day investment for
one line item at one company — the compensating-reversal ticket (Epic 1.7)
already proves the underlying "corrected-without-mutation money movement"
signal that actually gets probed in an interview. If Loop specifically is
being targeted later, it's the clean next step after Week 2, wrapping the
outbox/event flow that will already exist by then.

---

## Iteration 3 — Document Intelligence Chat MVP (Days 1–6, hard cap)

**Deprioritized to Iteration 3, not cut.** Of the 6 real JDs behind this
reordering, only Wagepoint touches tax/document work, and Wagepoint names
.NET/C# as its backend — a stack mismatch regardless. This work is still
real, still worth building (it's the genuine agentic-AI/RAG demonstration,
and MediCoord's own healthtech traction shows domain-specific AI work does
land), it's just not the fastest path to *fintech-specific* resume signal,
which is what Weeks 1–2 were reordered to optimize for.

**Do not start until Week 2 has shipped and been evaluated with real slack time remaining. This is load-bearing, not a suggestion.**

**Revised from an earlier 4-day, extraction-only version of this backlog.**
That version had the product goal backwards — it treated structured field
extraction as the core deliverable and RAG chat as an optional stretch. The
actual goal is a chat-based assistant a user can ask questions of and get
cited answers from; that requires chunking, embedding, retrieval, and
generation as baseline scope. 6 days is the honest cost of that, not 4 —
flagging the increase rather than quietly absorbing it.

### Epic 2.1 — `documents` table, ingestion, extraction (Day 1)
- [ ] `documents` table: id, source_type (`tax_slip`), storage_ref, ingested_at, status (`pending`|`needs_review`|`indexed`)
- [ ] **Raw document storage, decided explicitly, not left as a bare `storage_ref` column with nothing behind it.** S3, one bucket dedicated to this project, server-side encryption (SSE-S3 is sufficient — SSE-KMS is defensible but not required to make the point), bucket policy scoped to the service's own IAM role only (no public access, no broad account-wide read). State a real retention policy in the README even if it's simple for a portfolio project (e.g. "documents deleted N days after ingestion, or manually after the review period") — the point is that it's a stated decision, not an open question.
- [ ] Assemble a small fixed sample set of tax documents (T4/W-2/1099-style) — a mix of clean and deliberately messy/scanned ones, enough to exercise the confidence path
- [ ] **Verify every sample document is genuinely single-page before relying on it.** Textract's synchronous `AnalyzeDocument` API only processes page one of a multi-page PDF/TIFF — a multi-page scanned W-2/1099 packet in the sample set will silently lose pages 2+ with no error. Either constrain the sample set to real single-page files, or add a page-split preprocessing step before Textract. Decide this now, not when a messy sample turns out to be a 3-page scan mid-build.
- [ ] Textract integration (synchronous API — AnalyzeDocument) to get raw text + per-region confidence scores out of each document
- [ ] **Timeout + retry policy on the Textract call, stated as real numbers** (e.g. N-second timeout, exponential backoff, max M attempts) — not left to boto3's defaults, which can hang a request longer than acceptable.
- [ ] **Run Textract calls off the FastAPI event loop** (`anyio.to_thread.run_sync` / `run_in_executor`) — boto3 is synchronous, and an in-loop multi-second Textract call blocks the entire async event loop, including concurrent `POST /postings` requests to the ledger in the same process. Bound the number of concurrent ingestion jobs so they can't starve the shared DB connection pool either.
- [ ] **Mock the boto3 Textract client in unit/integration tests** — real calls in CI are flaky, slow, and cost money per run. Reserve real Textract calls for a manual or nightly-scheduled run against the actual sample set.

### Epic 2.2 — Chunking, confidence filtering, indexing (Day 2)
- [ ] **Chunk by Textract's own LAYOUT block boundaries** (Textract's Layout feature identifies section headers, paragraphs, tables, key-value pairs) — treat each layout-identified section as a chunk boundary, keep TABLE blocks intact as their own single chunk rather than letting one straddle a boundary. This is the concrete implementation of "structure-aware": use Textract's own structural output, don't reinvent a heuristic from scratch.
- [ ] Confidence filtering at chunk level: text from low-confidence OCR regions is excluded from the indexed corpus (or explicitly flagged), so the assistant never confidently answers from garbled text. Capture and justify the real threshold used.
- [ ] **Confidence-filter drop-rate metric**: log what fraction of the corpus gets excluded at ingestion. Without this, a bad OCR run degrading retrieval quality looks identical to "the model just isn't finding it" — this is what makes the difference diagnosable.
- [ ] **Name and pin the embedding model explicitly in the migration** (e.g. OpenAI `text-embedding-3-small`, or whichever LiteLLM-routed model) — pgvector requires a fixed `vector(N)` dimension declared at migration time, and changing the model later means a full re-embed, not a config change.
- [ ] **Match the distance metric/operator class to what the chosen model expects** (cosine vs. L2 vs. inner product). Getting this wrong doesn't error — it returns plausible-looking but wrong-ranked results, which only the golden-set eval (Epic 2.6) would catch, and only if someone notices citations look off.
- [ ] **No ANN index (HNSW/IVFFlat) at this corpus size — state this as a decision, not an oversight.** A sample-set-sized corpus (dozens to low hundreds of chunks) should use exact sequential scan; IVFFlat specifically gives worse recall with too few rows relative to its `lists` parameter. Note the revisit trigger in the README (e.g. "add HNSW if corpus exceeds ~X chunks") so it reads as considered, not missed.
- [ ] **Re-embedding on reprocessing**: detect content change via a hash on the extracted text; if a document is re-OCR'd or re-ingested, garbage-collect its stale chunks/vectors rather than accumulating duplicate or contradictory entries in the index under the same document.
- [ ] Embed chunks, index into pgvector on the same Postgres instance, storing document id + page + location alongside each chunk (this is what makes citation possible later)

### Epic 2.3 — Retrieval + generation chat endpoint (Day 3)
- [ ] One chat endpoint: takes a question, retrieves top-k relevant chunks from pgvector, generates an answer
- [ ] Every answer cites the retrieved chunk's document/page/location — no answer without a citation
- [ ] Route the generation call through **LiteLLM**
- [ ] **Timeout + retry policy for the LiteLLM generation call, and a defined behavior on upstream rate-limit/error** (a fallback model configured in LiteLLM's routing, not a raw 500 to the user) — provider hiccups are the single most common real-world chat-path failure and nothing here addresses it otherwise.
- [ ] If retrieval returns nothing above a relevance threshold, the assistant says so explicitly rather than answering from general knowledge — same fail-safe-over-fabrication principle as MediCoord's Beat 4, applied to a new domain
- [ ] **Per-query logging**: retrieved chunk IDs, similarity scores, LLM token usage, and latency, for every chat turn — without this a bad answer can't be debugged after the fact, only reproduced live.
- [ ] **Mock LiteLLM's generation call in unit/integration tests**, same reasoning as Textract — real calls are flaky, slow, and cost money in CI.

### Epic 2.4 — Minimal chat UI (Day 4)
- [ ] A simple, usable chat interface in React (Vite scaffold, no extra framework) wired to the Epic 2.3 endpoint — a person should be able to open it, ask a question about an ingested document, and see the cited answer
- [ ] This is the "visible product" deliverable that distinguishes Sprint 2 from Sprint 1's PoC — polish is not the bar, a working demo is

### Epic 2.5 — Agentic tool-calling into the deterministic rule engine + ledger (Day 5)
- [ ] Deterministic rule engine: one computed value in scope (e.g. total reported income, or a withholding sum), implemented as a pure function — no LLM call anywhere inside it
- [ ] **Rule versioning: `rule_versions` table, same Postgres instance, same append-only pattern as `postings`** — id, rule_name, version_number, logic reference, effective_date, created_at; a rule is never edited in place, only superseded by a new version row. This is a correctness decision, not a cost-saving one: keeping rule resolution inside the same transactional boundary as the ledger it computes for avoids introducing a second source of truth (an external store resolved via a network call) into the one part of the system meant to be transactionally certain. An S3-object-versioning-plus-ARN-pointer design was considered and rejected for exactly this reason — it would resolve a rule at read time through a different system, adding a network hop and a consistency question into the ledger's own computation path.
- [ ] Wire it as a **tool** the chat assistant can call when a question needs a computed figure, not free-text math the LLM does itself — mirrors MediCoord's own "tool call before free text" pattern, applied to money instead of medical facts
- [ ] **The tool's signature takes only a document/extraction reference (`document_id`), never an amount as a free-form argument.** The rule engine always re-derives the figure server-side from that document's own confidence-validated extraction record — never from anything the model states or passes in. This closes the action-authorization gap by construction: there is no code path where a number the model asserts, or a figure a crafted document tries to influence via the conversation, can reach the tool call. This is the concrete answer to "is the boundary enforced by code or by hope."
- [ ] **`tool_invocations` table — immutable, append-only, same pattern as `postings`/`rule_versions`**: id, session_id, tool_name, document_id, result, created_at. This is the audit trail the cross-check below depends on; without this table existing first, "cross-check against a logged record" has nothing to check against.
- [ ] **Prompt-injection defense: a dual-LLM pattern, not text sanitization.** MediCoord's existing sanitization (stripping delimiter-escape characters) defends against *output-integrity* attacks; this system's exposure is *action-authorization* — a crafted document causing a wrong figure to reach the ledger via an innocuous question. Concretely: a first LLM pass receives the raw retrieved document chunks and has **no tool definitions available to it at all** (not "instructed not to use tools" — structurally cannot call any), and produces a sanitized summary/extraction. A second LLM pass, the one with tool access, receives only the first pass's sanitized output — never the raw chunks directly. This breaks the chain because no single model invocation ever holds both untrusted document content and tool-calling ability at once.
- [ ] **Force `tool_choice` for known computable-figure question patterns rather than leaving invocation to model discretion.** LLMs skip tool calls when a question is phrased slightly differently than expected — relying purely on judgment means the safety property is probabilistic, not guaranteed.
- [ ] **Cross-check at answer-render time: any numeric claim in the response attributed to the tool must have a corresponding row in `tool_invocations` for that turn.** Without this, a hallucinated tool result narrated in the model's output text is indistinguishable from a real one.
- [ ] **Max-iteration / max-tool-call / token-budget cap on the agent loop.** Without a hard cap, a malformed or adversarial conversation can spin indefinitely burning LLM spend — a five-line guard, but it must exist before this touches a real API key.
- [ ] The tool can additionally post the validated figure to Sprint 1's ledger via the existing `POST /postings` (in-process call, not a network call), with an idempotency key derived from `(document_id, tool_invocation_id)` so asking the same question twice never double-posts — **verify `tool_invocation_id` is stable across the agent framework's own retries of the same logical call.** If the framework or LiteLLM mints a new ID per retry attempt, the idempotency key does nothing.
- [ ] Migration: add nullable `source_document_id`, `source_page`, `source_location` to Sprint 1's `entries` table — this is how a ledger posting made from a chat answer stays citable back to its source
- [ ] End-to-end test: ask the assistant a question requiring a computed figure, confirm the tool ran (not the LLM doing arithmetic inline), confirm a balanced, citable posting appears in the ledger

### Epic 2.6 — Eval + combined README (Day 6)
- [ ] Golden-set eval: 15-20 hand-written questions with expected citations, checked for correct retrieval, correct citation, and (for the subset needing it) correct tool invocation — not answer-quality grading
- [ ] **Adversarial ingestion test cases, three specific categories**: a garbage/corrupted document, a plausible-but-wrong scanned figure (a document engineered to produce a confident, incorrect extraction), and a mostly-clean document with one deliberately bad field. Assert the system's failure mode in each case (review-queue routing, rejection, or correct low-confidence handling) rather than a silent wrong answer.
- [ ] Capture the real result as-is, including failures
- [ ] One README covering both phases as one system: Sprint 1's stress-test numbers, Sprint 2's eval numbers, a note on what's proven vs. deliberately deferred
- [ ] Stop.

**If 6 days needs to shrink back toward Sprint 1's discipline:** cut Epic 2.5
(tool-calling + ledger tie-in) to a stretch first — Epics 2.1–2.4 alone are a
complete, demoable chat-over-documents product without it, just one that
doesn't connect back to the ledger. Do not cut Epic 2.4 (the UI) to save
time; a RAG pipeline with no visible product is Sprint 1's failure mode
repeating under a different name.

---

## Review history — VP Eng + CTO/Principal Eng passes (resolved 2026-08-30)

Every item surfaced across both review lenses (VP Eng persona rounds — hiring
signal — and a separate CTO/Principal Eng technical battle-test) has now been
folded into a concrete ticket in the epics above, not left as a loose
principle. For traceability:

- Tool-call/agent-action verification -> Iteration 3, tool-calling epic — document-reference-only signature
- Document storage/retention/encryption -> Iteration 3, ingestion epic — S3/SSE/IAM/stated policy
- Prompt injection (action-authorization) -> Iteration 3, tool-calling epic — dual-LLM pattern, architecture spelled out
- Immutable audit trail -> Iteration 3, tool-calling epic — `tool_invocations` table
- Adversarial ingestion testing -> Iteration 3, eval epic — 3 named categories
- Chunking strategy -> Iteration 3, chunking epic — Textract LAYOUT-block boundaries
- Reversal-of-a-reversal -> Week 1, Epic 1.7 — chains allowed, explicit decision + test
- Aurora deployment framing -> Week 1, Epic 1.6 — stated transparently in the README
- HTTPS/TLS -> stack table, cross-cutting
- Migration testing -> Week 1, Epic 1.8 — standing CI rule for every future migration
- RAG-specific fault injection / CI mocking -> Iteration 3, ingestion + chat epics
- RAG-specific observability -> Iteration 3, chunking + chat epics

**Genuinely still unscheduled, correctly deferred (P2, revisit only if real
traffic or volume ever shows up):**
- Chat-path load/latency testing under concurrent sessions — matters once there's real traffic, not before, and not relevant until Iteration 3 exists.
- Async ingestion job queue for large/slow documents — synchronous-in-request is acceptable at this sample-set scale.

Not a backlog item: **no signal on behavior under business/compliance
pressure.** This is an interview-prep gap (a live, unrehearsed pressure-
scenario rehearsal), not something buildable into the project itself —
tracked separately, not here.

---

## Icebox — considered and explicitly cut, check here first

If an idea comes up mid-sprint that isn't in the backlog above, it's very
likely already here. Adding anything from this list requires deliberately
reopening scope, not just doing it because it seems easy in the moment.

- **gRPC, a second service, a Node/NestJS+Fastify backend** — no evidenced hiring signal tied to transport/service-boundary choices in either research pass; doubles the build surface for a 2-sprint budget. Reconsider only as a separate, later project, not inside this one.
- **Version tracking** — zero evidentiary backing found anywhere in either research pass.
- **Building OCR robustness from scratch** (deskew, denoise, rotated pages, merged table cells) — use Textract's output and confidence scores as-is; this is a multi-week problem on its own.
- **A dedicated audit-trail subsystem** — Sprint 1's immutable postings plus structured logging already cover this claim.
- **Full two-track eval with live production sampling** — no real production traffic exists for a portfolio artifact to sample against.
- **Insurance documents, or any domain beyond tax, in this pass.**
- **A full saga orchestrator / multi-service compensating-transaction choreography, including Temporal.io specifically** — held even after Loop Financial's posting named Temporal.io directly (2026-08-30 JD review): running it credibly is a multi-day investment for one line item at one company, versus Epic 1.7's single-service compensating-reversal-posting proving the same underlying signal for near-zero cost. If a real orchestrator is wanted later, that's a third, separate project — the clean next step after Week 2's transactional outbox exists to wrap.
- **Full reconciliation subsystem against a live external settlement integration** — still cut, real signal, still genuinely out of scope for this size of build. **Partially reversed 2026-08-30**: a minimal version (one CSV fixture standing in for a settlement file, matched by reference, classified matched/unmatched/mismatched, no live second system) is now Week 2 Epic 2.2 — Chexy names "reconciliation" verbatim, and the minimal version doesn't carry the original rejection's cost.
- **Multi-currency, auth, any user-facing UI beyond what's needed to show a citation and a routing decision.**
- **S3 object versioning + ARN pointer for rule governance** — technically legitimate as a durability mechanism, rejected specifically because resolving a rule at read time through a different system (a network call to S3 via the AWS SDK) introduces a second source of truth and a consistency question into the ledger's own computation path. The `rule_versions` table (Epic 2.5) proves the same append-only governance principle inside the same transactional boundary, with no new infrastructure.
- **Streamlit or plain HTML/JS for the chat UI** — React is the locked choice; Next.js is a named, deliberate later-expansion option, not part of this build.
- **Competitive framing against Modern Treasury, Formance, or any named production platform.** "MVP" is accurate language for Sprint 2 specifically (it is one) — the original ban was about not overselling Sprint 1's PoC as more than an invariant proof; keep Sprint 1's README calling it a PoC, not an MVP.
