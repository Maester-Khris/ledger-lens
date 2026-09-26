# Fintech Ledger + Document Intelligence — Changelog

All notable changes to this project are documented in this file.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

Pre-2026-08-31 history belongs to this repo's original ML/hackathon project
(topic classification, model deployment pipeline) — a different product, not
carried forward. This changelog starts at the restart into the current
Fintech Ledger + Document Intelligence product.

---

## [Sprint — feat/demo-ready] · Release readiness before `/promote-release` — In Progress

**Started — 2026-09-26 · branch: `feat/demo-ready`.** Scope review on Monday 2026-09-28 decides
whether the sprint is extended. **Paused 2026-09-26** with the UI rounds done and verified in the browser;
the fintech-audience features below are next. Commits are local; not yet pushed, not ready for `/end-sprint`.

### Scope

- [ ] `assistant` — **key decision first:** the answer for a contract with no billing household (golden case `fund-not-comparable`) → **Not epic-tracked** (live-run finding)
- [x] `frontend` — human review loop: dashboard "to review" link → the fields awaiting review → decision logged append-only → **Not epic-tracked** (live-run finding)
- [ ] `ops` — tracing with Langfuse (`artifacts/research/2026-09-24-tracing-stack.md`) → **Epic 2.3** (Week 2)
- [x] `frontend` — UI fixes: chat message spacing, markdown rendering in answers, general pass → **Not epic-tracked** (live-run findings)
- [x] `frontend` — landing page copy: replace the tax-slip / Form 941 demo with the fee-contract product → **Not epic-tracked** (live-run finding)
- [x] `frontend` — ledger and dashboard read real data; approvals from chat and the review screen; keyboard selection, focus styles, live API status → **Not epic-tracked** (UI audit 2026-09-26)
- [x] `api` — `/reviews` queue and decisions over `field_reviews`; account names on posting and proposed entries → **Not epic-tracked** (UI audit 2026-09-26)
- [x] `frontend` — ledger logo in the app chrome; dashboard tiles and corpus telemetry on real stats; in-app pdf.js viewer on Documents and a two-pane, paginated Review → **Not epic-tracked** (UI review round 2, 2026-09-26)
- [x] `api` — cached `/stats` (TTL + invalidation + ETag) and `/config`; immutable caching for original PDFs → **Not epic-tracked** (UI review round 2, 2026-09-26)
- [ ] `audit` — real-time audit log → **Not epic-tracked** (fintech-audience feature, added 2026-09-26)
- [ ] `assistant` — behaviour under uncertainty: what the model does when an answer depends on an extracted field still awaiting review → **Not epic-tracked** (fintech-audience feature, added 2026-09-26)
- [ ] `ops` — key metrics from the tracing integration: tokens per query and result, response latency → **Epic 2.3** (with the Langfuse tracing item above)
- [ ] `test` — automated Playwright test: citation click shows the cited section with the quote highlighted (D18) → **Not epic-tracked**
- [ ] `documents` — security review of the redaction boundary; close the street-address gap before anything reaches OpenAI, Pinecone or traces → **Not epic-tracked** (live-run finding)

### Reference

- `artifacts/product-backlog.md` — "Next sprint — release readiness before `/promote-release`"

## [Sprint — feat/doc-intelligence] · Document Intelligence MVP on contracts

**Verified live 2026-09-24** against the real OpenAI and Pinecone, plus an end-to-end UI test in
Chrome. Golden set: numbers 1.0, refusals 0.875, citations 0.875 (`backend/reports/eval-fdfec82a79e3.json`).
268 automated tests.

### Completed

- `design` — re-scope from tax slips to investment advisory contracts (research D1–D19), design spec and three implementation plans → **Not epic-tracked** (PureFacts alignment; re-scopes Iteration 3)
- `documents` — PDF intake checks (magic bytes, text layer; scans rejected with 422), content-addressed storage, append-only documents, versions and events → **Epic 2.1** (Iteration 3)
- `documents` — Docling parse into elements with page grades; Presidio PII tokens (deterministic HMAC, encrypted vault, spaCy `en_core_web_md`) before any text leaves the machine → **Epic 2.1** (Iteration 3)
- `ingestion` — staged worker pipeline (parse_redact → index → extract) with advisory locks, retries and an event log → **Epic 2.1** (Iteration 3)
- `contracts` — cited structured extraction; each field routed `accepted` or `needs_review` by grounding, validators and page grade; only accepted fields are served → **Epic 2.1**, **Epic 2.2** (Iteration 3)
- `retrieval` — current versions indexed into Postgres full-text and Pinecone; hybrid search with rank fusion, a stale-vector filter and a relevance gate (`MIN_DENSE_SIMILARITY` 0.43, calibrated on the live golden set) → **Epic 2.2**, **Epic 2.3** (Iteration 3)
- `assistant` — LangGraph agent streamed over SSE; every number in an answer verified against its citations; chat audit trail → **Epic 2.3** (Iteration 3)
- `assistant` — contract-fields and contract-vs-billing tools (IDs only, `fee_math` does the arithmetic), forced `list_documents` → compare sequence, and the leakage correction proposed for human approval; every call in `tool_invocations` → **Epic 2.5** (Iteration 3)
- `frontend` — documents and chat screens wired to ingestion and SSE chat; citation chips open the PDF on the cited page → **Epic 2.4** (Iteration 3)
- `eval` — golden set (8 Q&A plus extraction truths) and harness; privacy test proving no raw PII reaches embeddings or the chat model; end-to-end UI test → **Epic 2.6** (Iteration 3)
- `config` — every deployment, model and tuning setting read from `backend/.env` (`.env.example` lists them all) → **Not epic-tracked**
- `docs` — README live-run results and current status; backlog ticked → **Epic 2.6** (Iteration 3)

### Deferred

- `assistant` — **key decision:** show the tool's reason for a contract with no billing household, or keep the generic refusal and change the golden case → **Not epic-tracked** (live-run finding)
- `frontend` — chat message spacing, broken review path (dashboard link to an all-green page), markdown rendering in answers and quotes, landing page copy → **Not epic-tracked** (live-run findings)
- `documents` — parser heading nesting, sample title mismatch, highlighting the quoted text on the PDF (D18) → **Not epic-tracked**
- `ops` — tracing and observability → **Epic 2.3** (Week 2)
- `eval` — CI eval gate, LLM-judge escalation cascade, review UI for `needs_review` fields → **Not epic-tracked** (specified in the spec, not built)
- `assistant` — agent serving upgrade (worker + Postgres checkpointer + resumable stream) → **Not epic-tracked**
- `infra` — Aurora deployment → **Epic 1.5**

## [Sprint — feat/ledger] · Ledger hardening + revenue book of record

### Completed

- `design` — industry research (`artifacts/research/2026-09-22-ledger-engineering.md`) and sprint spec → **Not epic-tracked** (PureFacts alignment)
- `db` — Postgres 18, owner/app roles, tests run as the least-privilege role → **Epic 1.1**
- `db` — append-only history, per-currency balance, ≥1 debit/credit, tenant and mirror checks in Postgres → **Epic 1.2**
- `api` — idempotent `POST /postings` with fingerprints, replay/422/409/400 contract, read endpoints → **Epic 1.3**
- `test` — concurrency proof against a live multi-worker server → **Epic 1.4**
- `api` — compensating reversal endpoint → **Epic 1.7**
- `billing` — households, versioned fee schedules (temporal keys), reproducible fee runs → **Not epic-tracked** (PureFacts alignment)
- `governance` — AI tool-invocation audit and human approval before posting → **Epic 2.5** (governance tables; chat wiring deferred)
- `reporting` — reproducible GL-ready export → **Not epic-tracked** (PureFacts alignment)

### Deferred

- `infra` — Aurora deployment (verify Postgres 18 support) → **Epic 1.5**
- `ops` — correlation-ID logging + CI gate → **Epic 1.8**
- `billing` — fee corrections (reverse and re-bill), advisor compensation → **Not epic-tracked**
- `recon` — statement-vs-ledger reconciliation matcher → **Epic 2.2**

## [Sprint 2 — Closed] · Ledger DB Core

**Closed — 2026-09-06.** Epics 1.1 and 1.2 fully shipped, database side only.
No feature branch — predates `/start-sprint`/`/end-sprint` tooling, committed
directly to `preview` (2026-09-06).

### Completed

- `design` — ledger DB core design spec + validating schema research (three-table
  shape, direction-enum vs. signed-amount decision) → informs **Epic 1.1, Epic 1.2**
- `chores` — implementation plan for the ledger DB core → **Epic 1.1, Epic 1.2**
- `db` — `accounts`/`postings`/`entries` schema → **Epic 1.1**
- `db` — Alembic environment wired to app config → **Epic 1.1** (migration tool decided and wired)
- `db` — DB dependencies and `DATABASE_URL` config → **Epic 1.1**
- `db` — idempotent local Postgres setup script (`db_up.sh`) → **Epic 1.1** (local dev setup)
- `db` — deferred constraint trigger enforcing posting balance — a real
  `CREATE CONSTRAINT TRIGGER ... INITIALLY DEFERRED`, not a plain `AFTER
  INSERT` trigger → **Epic 1.2**
- `db` — DB session factory (SQLAlchemy 2.0 autobegin semantics) → **Epic 1.2** (atomic write pattern)
- `db` — ledger DAO (`create_account`, `create_posting`) + balance-invariant
  tests → **Epic 1.2** (unit tests: balanced succeeds, unbalanced rejected, zero partial rows)
- `db` — migrations wired into `db_up.sh`, local setup documented in README → **Epic 1.1**

### Deferred

- `api` — `POST /postings` idempotent endpoint → **Epic 1.3**
- `db` — concurrency + idempotency stress test → **Epic 1.4**
- `infra` — Aurora deployment → **Epic 1.5**
- `docs` — README with captured stress-test numbers → **Epic 1.6**

### Reference

- `docs/superpowers/specs/2026-09-06-ledger-db-schema-design.md`
- `docs/superpowers/plans/2026-09-06-ledger-db-core.md`
- `artifacts/ledger-schema-research.md`
- `artifacts/product-backlog.md` — Epics 1.1–1.6 (Week 1 — Ledger Core)

---

## [Sprint 1 — Closed] · UI Design Pipeline & Static Frontend

**Closed — 2026-09-05.** Design-to-mockup-to-static-UI pipeline completed and
shipped. **Not epic-tracked** — this work predates `artifacts/product-backlog.md`'s
epic numbering (which only covers the ledger core and document-intelligence
phases); no backlog epic exists to link these items to.
No feature branch — predates `/start-sprint`/`/end-sprint` tooling, committed
directly to `preview` (2026-09-03 to 2026-09-05).

### Completed

- `design` — UI design pipeline spec (competitor research → template → Stitch → static React)
- `design` — UI research artifacts: competitor UX analysis, template sourcing,
  Stitch prompts + generation log
- `frontend` — static React UI for landing, dashboard, chat, documents, and
  ledger screens
- `frontend` — motion and visual polish on the landing page
- `frontend` — OpenGraph integration, continued landing page redesign

### Reference

- `docs/superpowers/specs/2026-09-03-ui-design-pipeline-design.md`
- `artifacts/ui-research/` — competitor-ux.md, template-selection.md, stitch-prompts.md
- `artifacts/ui-research/stitch/` — shipped mockups (chat, dashboard, landing, ledger-postings)

---

## [Restart] — 2026-08-31

Repo restarted as Fintech Ledger + Document Intelligence — a double-entry
ledger core paired with a document-intelligence chat feature, replacing the
prior ML/hackathon project in this repository.
