# Fintech Ledger + Document Intelligence — Changelog

All notable changes to this project are documented in this file.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

Pre-2026-08-31 history belongs to this repo's original ML/hackathon project
(topic classification, model deployment pipeline) — a different product, not
carried forward. This changelog starts at the restart into the current
Fintech Ledger + Document Intelligence product.

---

## [Sprint — feat/pre-launch-demo] · Pre-launch demo: safe to publish, and evidence of real use — In Progress

**Started — 2026-09-29 · branch: `feat/pre-launch-demo`.** Hosting decided: Vercel (frontend) and Railway
(API and Postgres 18 in one project); this replaces Aurora for the demo. Order below is the agreed
build order.

> **✅ DECIDED 2026-09-29: guest decisions go to a per-guest overlay (P9), built in this sprint right after P2.**
> Approvals are permanent and global today, so one guest's decision changes every other guest's answers.
> Revert-at-session-end was rejected (committed data is visible until the revert lands; a reversal pair
> stays in the append-only ledger). Guest decisions go to disposable overlay tables merged at read time;
> tool approvals run the posting check in a rolled-back transaction. Rationale in the backlog.
> **Until P9 lands: the deployed build accepts no public decisions and the demo is not announced publicly.**

### Scope

- [ ] `ops` — P1 deploy skeleton first: Railway API and Postgres 18, Vercel frontend, `ledger_owner` migrates and `ledger_app` runs the API, direct CORS calls, Infisical secrets, SEC documents loaded → **Epic 1.5** (replaced by Railway for the demo; Aurora stays open for a non-demo deploy)
- [ ] `api` — P2 demo mode cannot ingest: ingestion routes unmounted and the demo DB role has no insert on document tables → **Not epic-tracked** (pre-launch triage, backlog P2)
- [ ] `contracts` — P9 phase 1: per-guest field-review overlay merged into every reader of `field_reviews`, gated by `DEMO_MODE` → **Not epic-tracked** (guest-decision overlay, backlog P9)
- [ ] `governance` — P9 phase 2: per-guest tool-approval overlay, rolled-back posting check, the guest's simulated entries in Ledger and timeline → **Not epic-tracked** (guest-decision overlay, backlog P9)
- [ ] `api` — P3 per-guest rate limit and provider spend caps (OpenAI, Pinecone, Railway), plus CORS locked to `FRONTEND_URL` (`https://ledgerlens.nknext.dev`) with `X-Guest-Id` allowed; the deployed frontend cannot call the API until it lands → **Not epic-tracked** (pre-launch triage, backlog P3)
- [ ] `assistant` — P4 retrieval edge cases: send disabled on empty, explicit "no supporting passage found" → **Not epic-tracked** (pre-launch triage, backlog P4)
- [ ] `api` — P5 thumbs up/down and comment feedback, stored per guest and chat turn → **Not epic-tracked** (pre-launch triage, backlog P5)
- [ ] `ops` — P6 Sentry on backend and frontend → **Epic 2.3** (backlog P6)
- [ ] `ops` — P7 minimal usage event log: client-measured latency, outcome, feedback → **Epic 2.3** (backlog P7)
- [ ] `frontend` — P8 document list with one-line descriptions and starter questions → **Not epic-tracked** (pre-launch triage, backlog P8)
- [ ] `design` — compressed 4-day design sprint on P4, P5, P8, then 5-person test of the journey map → **Not epic-tracked** (pre-launch triage)

### Infrastructure blockers (inside P1; found 2026-09-29, each would break the public demo silently)

- [ ] `ops` — **Original PDFs on ephemeral disk.** `DOCUMENT_STORE_DIR` defaults to `var/documents` (`originals/<sha>`); a Railway container loses it on redeploy, breaking the viewer and every citation click. Fix: attach a Railway volume and copy the originals into it during P1. Object storage isn't needed at this scale → **Epic 1.5**
- [ ] `ops` — **Separate demo Pinecone index.** The namespace is the tenant id, the same fixed demo tenant locally and on Railway, and re-indexing deletes old vector ids, so a local re-ingest would change the live demo. Fix: give the demo its own `PINECONE_INDEX`, fill it from the frozen corpus, and never point local ingestion at it. The existing scripts (`backend/scripts/create_pinecone_index.py`, `backend/scripts/ingestion_worker.py`, `scripts/delete_pinecone_namespace.py`) read the index from `PINECONE_INDEX`, so setting it targets the demo index → **Epic 1.5**
- [ ] `db` — **Roles on Railway Postgres.** With the Railway superuser, create `ledger_owner` and `ledger_app`, then run migrations as `ledger_owner`. Routine, but a step; P2 and P9 add grants on top → **Epic 1.5**
- [ ] `ops` — **Build the demo locally, then ship the database.** Launch the full infra on local (a demo database + the demo Pinecone index), ingest the frozen corpus into both, then dump the demo database and restore it onto Railway. Vectors and citations reference element UUIDs, and PII tokens are HMAC'd, so Railway must run with the same `PII_HMAC_KEY` / `PII_VAULT_KEY` (Infisical) and must never be re-ingested separately. **Run these only after the local demo ingest is done** (schema already comes from `alembic upgrade head` as `ledger_owner`, so the dump is data only; the superuser restore with `--disable-triggers` keeps the append-only and deferred balance triggers from tripping on load order):
  ```bash
  pg_dump --data-only --exclude-table=alembic_version --disable-triggers -Fc <local-demo-db> -f demo.dump
  pg_restore --data-only --disable-triggers -d '<railway superuser public URL>' demo.dump
  ```
  Then copy the matching originals into the Railway volume, and compare row counts → **Epic 1.5**
- [ ] `chores` — **Split requirements into worker and API.** `backend/requirements.txt` carries Docling and Presidio for ingestion; split into API and worker files and deploy only the API set on Railway (the worker is never hosted). `$PYDEV` locally keeps both → **Epic 1.5**
- [ ] `ops` — **Separate Langfuse project for the demo.** Keep the current Langfuse project for local work; create a new project `demo-ledglens`, and the Railway deploy uses its keys → **Epic 2.3**

### Reference

- `artifacts/product-backlog.md` — "Pre-launch sprint"
- `artifacts/pre-launch-demo-design-sprint.md` — design sprint plan and journey self-check (local file, not tracked)
- `artifacts/pre-demo-launch-candidates.md` — the raw candidate list (local file, not tracked)

## [Sprint — feat/demo-ready] · Release readiness before `/promote-release` — Closed

**Started — 2026-09-26 · branch: `feat/demo-ready`.**
**Closed — 2026-09-29.** Merged into `preview` as PR #8 (`9c50726`, 92 commits). The three unchecked scope
items below moved to Deferred; the next sprint is `feat/pre-launch-demo`.

### Scope

- [x] `assistant` — **key decision first:** the answer for a contract with no billing household (golden case `fund-not-comparable`) → **Not epic-tracked** (live-run finding). Decided option A, built with N11: a fixed message with a `system` citation; the golden case gets `expect_system_notice`
- [x] `frontend` — human review loop: dashboard "to review" link → the fields awaiting review → decision logged append-only → **Not epic-tracked** (live-run finding)
- [x] `ops` — tracing with Langfuse (`artifacts/research/2026-09-24-tracing-stack.md`) → **Epic 2.3** (Week 2). Built 2026-09-27 (one trace per chat turn and per extraction run, `chat_turns.trace_id`, tracing off without keys and in tests, PII boundary tested). Live-verified 2026-09-29 against the re-ingested corpus — see below
- [x] `frontend` — UI fixes: chat message spacing, markdown rendering in answers, general pass → **Not epic-tracked** (live-run findings)
- [x] `frontend` — landing page copy: replace the tax-slip / Form 941 demo with the fee-contract product → **Not epic-tracked** (live-run finding)
- [x] `frontend` — ledger and dashboard read real data; approvals from chat and the review screen; keyboard selection, focus styles, live API status → **Not epic-tracked** (UI audit 2026-09-26)
- [x] `api` — `/reviews` queue and decisions over `field_reviews`; account names on posting and proposed entries → **Not epic-tracked** (UI audit 2026-09-26)
- [x] `frontend` — ledger logo in the app chrome; dashboard tiles and corpus telemetry on real stats; in-app pdf.js viewer on Documents and a two-pane, paginated Review → **Not epic-tracked** (UI review round 2, 2026-09-26)
- [x] `api` — cached `/stats` (TTL + invalidation + ETag) and `/config`; immutable caching for original PDFs → **Not epic-tracked** (UI review round 2, 2026-09-26)
- [ ] `audit` — real-time audit log → **Not epic-tracked** (fintech reframing, backlog D6)
- [x] `assistant` — behaviour under uncertainty: what the model does when an answer depends on an extracted field still awaiting review → **Not epic-tracked** (fintech reframing, backlog N11)
- [x] `api` — guests: `X-Guest-Id` attribution on chats, reviews and approvals → **Not epic-tracked** (fintech reframing, backlog N19)
- [x] `frontend` — chat optionally scoped to one document → **Not epic-tracked** (fintech reframing, backlog N12)
- [x] `frontend` — contract profile panel (structured client profile) → **Not epic-tracked** (fintech reframing, backlog N17)
- [x] `frontend` — audit panel in the chat session (rest refreshed) → **Not epic-tracked** (fintech reframing, backlog N13)
- [x] `frontend` — per-document ledger timeline (ingestion to posting) → **Not epic-tracked** (fintech reframing, backlog N14)
- [x] `docs` — source URLs added for every competitor claim used in demo copy; two unsourced claims corrected (Ethoca's acquisition price, the "zero-hallucination" guarantee's attribution) → **Not epic-tracked** (fintech reframing, backlog N5)
- [x] `frontend` — reframed copy for the fintech audience: billing reconciliation, extraction anomaly queue, AI decision audit trail, the citation promise, and a 3-layer (ops/governance/audit) narrative on the landing page → **Not epic-tracked** (fintech reframing, backlog N6-N10)
- [x] `frontend` — landing hero: animated ops/governance/audit product visual (CSS-only, respects `prefers-reduced-motion`) → **Not epic-tracked** (fintech reframing, backlog N18)
- [x] `docs` — "Fee Agreement Audit" demo script (the WealthBar/CI Direct BCSC enforcement pattern, reversed): contract → gap → proposal → approve → post, walked end to end live against the re-ingested corpus; no new seed data needed — `seed_demo.py`'s existing Tremblay fee-schedule/contract mismatch (0.85% contract vs 0.80% billing, $400/year) is the gap the script demonstrates → **Not epic-tracked** (fintech reframing, backlog N15)
- [ ] `ops` — key metrics from the tracing integration: tokens per query and result, response latency → **Epic 2.3** (with the Langfuse tracing item above)
- [ ] `test` — automated Playwright test: citation click shows the cited section with the quote highlighted (D18) → **Not epic-tracked**
- [x] `documents` — security review of the redaction boundary; close the street-address gap before anything reaches OpenAI, Pinecone or traces → **Not epic-tracked** (live-run finding). Done 2026-09-27: street addresses and postal codes tokenised in documents; unknown emails, phones, SINs, cards, IBANs, addresses and postal codes tokenised in chat questions (Luhn-checked, amounts and fee terms left readable). Report: `artifacts/research/2026-09-27-redaction-boundary-review.md`

### Required once the demo-ready state is reached — done 2026-09-29

- [x] **Clear the database and re-ingest every document.** `documents` (and everything cascading from it — versions, elements, extraction runs, chat turns, tool invocations, guests) is append-only at the trigger level (`forbid_mutation()`), so this meant dropping and recreating `ledger_dev` itself (`DROP DATABASE ... WITH (FORCE)`; `ledger_test` untouched), re-running all 12 migrations, reseeding billing via `seed_demo.py`, clearing the stale Pinecone namespace (137 orphaned vectors — `scripts/delete_pinecone_namespace.py`, new script, parameterized by namespace) and the on-disk originals cache, then re-uploading the 4-document demo corpus (`nomura-tax-free-colorado-ima`, `aim-global-trends-advisory`, `calamos-emerging-market-equity`, `tremblay-ima`) and re-running the ingestion pipeline. All 4 reached `ready`. Confirmed `STREET_ADDRESS`/`POSTAL_CODE` tokens present in `pii_tokens` and absent from `document_elements.text_redacted`, with one residual NER recall miss noted (a Quebec-format residential address in the synthetic Tremblay agreement wasn't caught, while a US-format business address in the same run was — Presidio recall gap, not a regression). The pre-fix `e2e-okafor-agreement` test upload (not backed by any script/fixture) was not recreated. Then **re-ran the golden set**: first pass surfaced a real (pre-existing, unrelated to re-ingestion) test-harness bug — `tests/eval/test_golden.py` read `PII_HMAC_KEY`/`PII_VAULT_KEY` via `config.require(...)`, which the session-scoped `document_settings` autouse fixture overwrites with random per-run keys for hermetic unit tests; whenever an eval case's cited quote happened to contain a real vault token, decrypting it with the wrong key crashed the turn (`cryptography.fernet.InvalidToken`). The bug was latent before — the pre-reset corpus's citation boundaries never happened to include a tokenised substring — and was only exposed because re-extraction changed the `calamos-top-tier` case's returned quote to include one. Fixed (`tests/eval/test_golden.py`: read the real keys from `os.environ` directly, bypassing the fixture). After the fix: `refusal_ok 1.0, citation_hit 1.0, numbers_ok 1.0` on two consecutive runs — an improvement over the 2026-09-24 baseline (0.875/0.875), correctly reflecting the N11 fix for `fund-not-comparable`. Extraction field accuracy 9/12, unchanged.
- Accepted gap: a person's name typed in chat that appears in no ingested document is sent to the model untokenised.
- Deferred gaps: account numbers (other than IBAN / US bank numbers) and dates of birth are not tokenised.
- [x] **Live tracing run** (against the re-ingested corpus): confirmed a `chat`-tagged trace (`session_id` matches, 26 observations covering graph steps and model calls) whose Langfuse trace id matches `chat_turns.trace_id` in Postgres exactly, and `extraction`-tagged traces whose `run_id` metadata matches `extraction_runs.id`.

### Deferred

- [ ] `audit` — real-time audit log → **Not epic-tracked** (fintech reframing, backlog D6)
- [ ] `ops` — key metrics from the tracing integration: tokens per query and result, response latency → **Epic 2.3**
- [ ] `test` — automated Playwright test: citation click shows the cited section with the quote highlighted (D18) → **Not epic-tracked**

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
