# Fintech Ledger + Document Intelligence — Changelog

All notable changes to this project are documented in this file.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

Pre-2026-08-31 history belongs to this repo's original ML/hackathon project
(topic classification, model deployment pipeline) — a different product, not
carried forward. This changelog starts at the restart into the current
Fintech Ledger + Document Intelligence product.

---

## [Sprint — feat/measured-evidence] · Measured evidence: corpus, cost, scale, abuse — In Progress

**Started — 2026-10-15 · branch: `feat/measured-evidence`.** Goal: every number we quote in a public defense
(interview, peer or technical review) comes with its method, where it ran, sample size and limit. First use: the
Zown round 3 interview on Mon 2026-10-19. Code is the means, not the goal. Code freeze **Sun 2026-10-18 12:00**;
after it, write-up only.

> **Order rule.** Every **Now** item must pass its "done when" check before any **Next** item starts.
> **Line in the sand:** if N0, N0.1 and N1–N3 are not done by **Fri 2026-10-16 20:00**, N4 is dropped and we present
> the measured baseline plus the plan. If the 5-document N0 trial needs code fixes, N0 is capped at whatever ingests
> cleanly by Fri 12:00, and that count is what we quote.

### Scope — Now (blocks the goal, in order)

- [x] `documents` — **N0** corpus volume on the type the pipeline already handles: about 50 SEC EDGAR investment
      advisory agreements (fund-level, exhibit (d) to Form N-1A / 485BPOS) through `scripts/prepare_samples.py` and the
      ingestion worker, into the local database and a **local** Pinecone index (never `contract-demo`). Trial on 5
      documents first. Done when: corpus count, extraction accepted / needs_review counts and ingestion time and $ per
      document are recorded → **Not epic-tracked** (mentor review 2026-10-09: four documents is too small; sourcing in
      `artifacts/research/2026-10-09-client-onboarding-documents-wealth.md`)
      **Done 2026-10-15 (local):** 102 documents, all extracted, 0 failed: 101 real EDGAR filings (89 advisory, 8
      sub-advisory, 4 unlabelled trial filings) and 1 synthetic. Target raised from 50 to 100 on 2026-10-15. Discovery
      by EDGAR full-text search (485BPOS exhibit (d), 2020-01-01 to 2026-10-15), one filing per fund family, kept only
      with a single fee schedule (1 to 12 rate figures): 94 kept of 151 families checked. A 5-document trial ran first
      with no code fix needed. Ingestion: 93 documents in 36.6 min on one local worker (about 24 s each). Extraction:
      859 fields accepted, 758 routed to review (53% accepted); fee schedule valid on 18 of 102. Flat fees (one rate
      on all assets, the usual ETF shape) are now accepted when the band says what the rate applies to. One command:
      `backend/scripts/corpus_build.sh <discover> <upload>`; report `backend/reports/corpus-2026-10-15.json`. Limit:
      one document type, fund-level agreements (not retail client agreements), US only, local only until X0.
- [x] `assistant` — **N0.1** golden gate re-run on the expanded corpus (49 cases: 28 answerable including 12 re-asked scoped to their document, 21 junk). Done when: a report
      under `backend/reports/` names the corpus size it ran on. A drop is reported, not hidden → **Not epic-tracked**
      **Done 2026-10-15 (local, 102 documents, threshold 0.43):** passed 3 of 3 runs (`20261015-r1` to `r3`): answerable
      28/28 on behaviour, citation and numbers, over-refusal 0, junk 21/21, no provider retries; turn time median
      3.7 to 4.2 s, p95 6.0 to 7.3 s. Reports `backend/reports/eval-8e192f7302ee-20261015-r{1,2,3}.json`; resumable
      runner `backend/scripts/gate_runs.sh <runs>`. Limit: the local `.env` sets the threshold to 0.43 (an older
      calibration); the demo and the code default use 0.46. A stricter threshold can only refuse more, so junk holds;
      answerable cases at 0.46 are not measured yet. Golden questions name the original 4 documents.
- [ ] `ops` — **N1** cost per answer from Langfuse (already wired; the price entry for `gpt-4.1-2025-04-14` is
      confirmed): golden set replayed 3 times on the expanded corpus, local Langfuse project. Done when: median and p95
      $ per answer and per session, steps per answer and the most expensive step are recorded, cross-checked against
      the token counts in `chat_turns` → **Epic 2.3**
      **Partial 2026-10-15:** measured from the token counts stored per turn (`chat_turns`), priced at gpt-4.1 list
      price ($2 in / $8 out per million tokens): per answer median **$0.037**, p95 $0.054, max $0.099 (150 turns);
      per session median $0.037, p95 $0.056 (147 sessions); $1.19 to $1.30 per 49-case run; median 18,391 input and
      85 output tokens per turn. Same prompt and graph version (`a4782adc4015`, v3) on the 4-document corpus
      (2026-10-03): median 2,952 input tokens and $0.0067 per turn, so **cost per answer rose 5.3x with the corpus**.
      Ingestion: $1.32 for 98 extraction calls (median $0.012, p95 $0.022 per document; Langfuse); embeddings about
      $0.003 (estimate). **Open:** steps per answer and the most expensive step need Langfuse traces, which the runs
      did not send (see Deferred).
      **Cross-check against the OpenAI balance:** $10.00 of credit before the N0 ingestion, $7.46 after N0 and the
      three N0.1 runs, so $2.54 was billed against about $5.06 computed at list price ($1.32 extraction + $3.74 chat).
      Not resolved yet; likely causes are OpenAI's automatic prompt caching (repeated prefixes such as the system
      prompt and the document list are billed at a discount, and the stored token counts include cached tokens) and
      the balance updating with a delay. The traced re-run records cached tokens per call and should settle it.
- [x] `ops` — **N2** the replayed LLM responses saved as fixtures; a provider mock built from them that reproduces
      their response times (OpenAI chat completions with tool calls and structured output, embeddings). Done when: mock
      mean and p95 turn time are within 10% of the real replay (MediCoord Sprint 22 method) → **Not epic-tracked**
      **Done 2026-10-15 (local):** `backend/scripts/load/mock_openai.py` plays the agent's real path (search, stop, a
      structured answer that quotes and cites the first passage), so citation checking passes for real; the API
      reaches it through `OPENAI_BASE_URL`. `LOADTEST_STUB_VECTORS=1` swaps Pinecone for a read-only stub serving
      current passages from Postgres. Calibrated with `backend/scripts/load/calibrate_mock.sh` against the 147 real
      N0.1 turns: chat call mean 1.25 s, sigma 0.55 gives median 3.69 s vs 3.86 s real (-4.4%) and p95 6.83 s vs
      7.11 s (-3.9%), the same in two runs of 49 turns. A test drives the real graph through the mock to a cited
      answer. **Deviation:** no response fixtures (the real runs sent no traces), so the mock writes its own answers
      and is matched on turn time, not per-call time. Limit: golden-set timing, not live provider latency or limits.
- [x] `ops` — **N3** k6 baseline, one instance, provider mock: ramp until turn p95 bends. Done when: break point,
      turns/s there, error rate and what saturated first (CPU, DB pool, thread pool) are recorded. A bad baseline is
      expected → **Not epic-tracked** (backlog X4, small load test)
      **Done 2026-10-15 (local):** one API process (8 cores, 15 GB), provider mock and stub index, 2 golden questions
      per conversation, 1 min per level. Throughput bends at **about 3 turns/s from 20 concurrent conversations**
      (p50 5.5 s, p95 7.7 s); at 40, same throughput with p50 11.9 s and p95 15.2 s; at 80 the run stopped itself
      with 5.9% of turns failed (37 of 627). API CPU stayed at or below 25%. First saturated: **the thread pool**, 12
      model calls in flight and never more (the sync graph nodes run in Python's default executor, min(32, cores+4)
      = 12; 12 threads / 1.25 s per call / 3.2 calls per turn = 3.0 turns/s). Second: **the DB pool**, 15 connections
      (SQLAlchemy default 5 + 10), each held for a whole turn by `run_turn`; the failures at 80 are its 30 s
      timeouts. Model calls already have timeouts (30 s per call, 60 s per turn). One command:
      `backend/scripts/load/run_chat.sh <label>`; table `backend/reports/load/2026-10-15-baseline.steps.md`.
      Limit: local, k6 shares the machine; mock reproduces golden-set timing, not provider limits.
- [ ] `api` — **N4** fix the first bottleneck N3 shows, then re-run for before/after. Suspects in order: blocking calls
      on the event loop (`run_turn` does sync DB work on it), the DB and thread pools, OpenAI SDK connection limits,
      LLM timeouts (already set: 30 s per call, 60 s per turn). Done when: the same ladder is re-run and both results
      are recorded → **Not epic-tracked**
- [ ] `docs` — **N6** one-page design for bot and agent defense: a challenge before an anonymous session, a per-guest
      token / $ budget sized from N1, the per-IP limits already built, identified agents through an API with their own
      quotas. Design only. Written after the freeze → **Not epic-tracked**
- [ ] `docs` — write-up after the freeze: the before/after one-pager, proof-sheet rows, and a README section
      "Measured numbers" filled from the table below → **Not epic-tracked**

### Scope — Next (only once every Now item has passed)

- [ ] `api` — **N5** chat rate limiter moved to Redis (in process memory per server today), sliding window kept;
      allows the request if Redis is unreachable. Done when: tests pass and counts stay exact on 2 replicas in Docker
      Compose. Until then, the cross-replica shared-state proof we quote is MediCoord's → **Not epic-tracked** (backlog P3)
- [ ] `ops` — **X0** the expanded corpus on the public demo: local demo ingest, dump and restore to Railway, the demo
      Pinecone index refilled. Until it lands, every corpus claim says "local" → **Epic 1.5**
- [ ] `documents` — **X1** automated ingestion quality verification (mentor review: no check that an extracted value
      is correct; "confidently wrong" extractions pass review today). The verifier is independent of the extractor:
      extraction stays on the parsed text, verification reads the **page image** with a different model; a
      disagreement routes the field to `needs_review`. Done when: per-field agreement rate on the expanded corpus, and
      the verifier's false-pass rate against a small hand-labelled set, are recorded. Raw page images reach a vision
      model, so the PII claim and its test are restated first
      (`artifacts/2026-10-09-azure-multidoc-ingestion-review.md`, sections 3.1 and 3.2) → **Not epic-tracked**
- [ ] `documents` — **X2** 2 to 3 synthetic Canadian household agreements (CAD, Ontario governing law, one over-billed,
      one clean), labelled synthetic → **Not epic-tracked** (review 2026-10-04: the corpus is US only)
- [ ] `api` — **X3** admission control (a fast "busy" answer past a turns-in-flight limit), then a 4-replica run with
      one replica stopped → **Not epic-tracked**

### Deferred

- `assistant` — the document list is re-sent on every model call within a chat turn: `list_documents` returns all
  102 titles and the tool result stays in the turn's message history. Likely cause of the 5.3x cost per answer
  (N1). To analyse, fix, then re-measure cost, if time allows after the Now items → **Not epic-tracked**
- `ops` — Langfuse tracing for the golden runs: `tests/conftest.py` turns tracing off for every test not marked
  `enable_tracing`, so the N0.1 runs sent no traces. Mark the golden test, re-run, then report steps per answer and
  the most expensive step with `backend/scripts/cost_report.py` → **Epic 2.3**
- `contracts` — fee schedules still fail validation on most new filings (fee-schedule bands accepted: 23 of 152).
  77 are flat fees where the model leaves the band text empty (kept in review on purpose: an empty band could be one
  row of a multi-fund table); 47 are tiered schedules worded "up to $X" or "between $X and $Y", which the parser
  does not read. Fix with the extraction prompt or the parser, then re-extract; belongs with X1 → **Not epic-tracked**

### Numbers this sprint must produce (source of the README section "Measured numbers")

Each row is quoted with all four parts or not at all. "Limit" lists what is already known; add what the run shows.

| Area | Number | Method | Sample | Known limit |
|---|---|---|---|---|
| Corpus | Documents ingested, by type and by origin (real / synthetic) | N0 ingestion log | all documents | One type (fund-level advisory agreements, not retail client agreements); US only unless X2 lands; local unless X0 lands |
| Corpus | Extraction accepted / needs_review per document; per-field agreement (X1) | Pipeline status; X1 verifier | all documents; hand-labelled subset for X1 | Without X1, "accepted" is the validators' verdict, not a verified correct value |
| Corpus | Ingestion time and $ per document | N0 timings, token counts | all documents | Local machine; one model |
| Corpus | Golden pass rate on the expanded corpus (answerable, junk) | N0.1 gate | 49 cases (28 answerable, 21 junk), 3 runs | Curated questions, not user traffic |
| Cost | Median and p95 $ per answer and per session; steps per answer; most expensive step | N1, Langfuse cost, cross-checked with `chat_turns` tokens | 3 replays of the golden set | Curated questions, not user traffic; list prices; one model |
| Scale | Break point (turns in flight and turns/s where p95 bends), error rate, first saturated resource | N3, k6 with the provider mock | one ladder run | One instance, local; mock reproduces golden-set timing, not live provider latency or rate limits; k6 shares the machine |
| Scale | Before/after at the break point | N4, same ladder | two ladder runs | Same as N3 |
| Abuse | Limiter counts exact across replicas (N5) | Docker Compose, 2 replicas | one run | Local; pass/fail correctness, not capacity |
| Abuse | Per-guest token / $ budget | N6, derived from N1 | n/a (design) | Design only, not built |

### Reference

- Plan: `rx-next/agents/rx/output/screening/zown/ledgerlens-update-plan_2026-10-14.md`; probe areas:
  `.../round3-probe-areas_2026-10-14.md`. Reordered on 2026-10-15 to put corpus volume first, since cost depends
  on the corpus (`list_documents` and the clarifying question grow with it).
- Load-test method, provider mock, Compose stack: MediCoord Sprint 21–22 (`medicoordai/backend/scripts/load/`,
  `medicoordai/artifacts/perf/2026-10-13-phase5-report.md`).
- Corpus critique and sourcing: `artifacts/2026-10-09-azure-multidoc-ingestion-review.md`,
  `artifacts/2026-10-04-review-first-reactions.md`, `artifacts/research/2026-10-09-client-onboarding-documents-wealth.md`.
- Cut until after Monday: multi-type ingestion (brochures, RDI, tax and identity forms), multi-region, auth, managed
  bot control, chaos tooling, dashboards, evals in CI.

---

## [Sprint — feat/pre-launch-demo] · Pre-launch demo: safe to publish, and evidence of real use — Closed

**Closed — 2026-10-15.** Merged into `preview` via `/end-sprint`, then promoted to `main`. P6 (Sentry), the
P3 spend caps, the design sprint and the Vercel Production switch moved to Deferred.

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

- [x] `ops` — P1 deploy skeleton first: Railway API and Postgres 18, Vercel frontend, `ledger_owner` migrates and `ledger_app` runs the API, direct CORS calls, Infisical secrets, SEC documents loaded → **Epic 1.5** (replaced by Railway for the demo; Aurora stays open for a non-demo deploy) **Done 2026-09-30:** API, Postgres 18 and the demo data on Railway; frontend on Vercel at `https://ledgerlens.nknext.dev`, which is assigned to the `feat/pre-launch-demo` branch (Production still points at the old `main` until the release is promoted); `VITE_API_BASE` set with the Vercel CLI for Preview on that branch; CORS live (`0eba28d`, `c3527b4`); smoke-tested in the browser: documents list, streamed cited chat answer, audit trail and dashboard. Secrets are set as Railway variables; Infisical was not checked here.
- [x] `api` — P2 demo mode cannot ingest or write the ledger: upload and the ledger-write routes (`/postings`, reversal, `/fee-runs`, `/gl-exports`) unmounted, and the `ledger_demo` DB role has no insert on document, extraction, ledger or real-decision tables; one spec with P9 (`docs/superpowers/specs/2026-09-30-demo-mode-and-guest-overlay-design.md`) → **Not epic-tracked** (pre-launch triage, backlog P2) **Done 2026-10-01:** `DEMO_MODE=1` and the API running as `ledger_demo` on Railway (migration 0013). Deployed checks: `POST /documents` and `/postings` answer 405, reversal, `/fee-runs` and `/gl-exports` 404; connected as `ledger_demo`, inserts into `postings`, `documents` and `field_reviews` fail with `permission denied`.
- [x] `contracts` — P9 phase 1: per-guest field-review overlay merged into every reader of `field_reviews`, gated by `DEMO_MODE` (same spec as P2) → **Not epic-tracked** (guest-decision overlay, backlog P9) **Done 2026-10-01:** deployed check with two guests on one field: A confirmed, B rejected, the shared view still `needs_review`; a second decision by A answers 409; a decision without a guest answers 400.
- [x] `governance` — P9 phase 2: per-guest tool-approval overlay, read-only `check_posting` (not a rolled-back posting), guest-scoped proposals, the guest's simulated entries in Ledger and timeline (same spec as P2) → **Not epic-tracked** (guest-decision overlay, backlog P9) **Done 2026-10-01:** `frontend/e2e/demo-approval.e2e.ts` (Playwright, `npm run test:e2e`) passes on `https://ledgerlens.nknext.dev`: upload hidden, the agent proposes a correction, "Approve (demo, not recorded)" ends in "Demo posting, not recorded", the Ledger lists it under "Your demo postings" with no reversal, a second visitor sees none of it; the database then held 1 guest approval, 0 real decisions, 0 AI postings.
- [ ] `api` — P3 per-guest rate limit and provider spend caps (OpenAI, Pinecone, Railway), plus CORS locked to `FRONTEND_URL` (CORS itself is done, see P1; rate limit and spend caps still open) → **Not epic-tracked** (pre-launch triage, backlog P3) **Rate limit done 2026-10-01:** in demo mode `POST /chat` is capped per guest (10) and per client IP (30) per 10-minute sliding window (`CHAT_LIMIT_*`), 429 with `Retry-After`; the IP is the rightmost `X-Forwarded-For` entry, the one Railway's edge appends (forged entries to its left are ignored); in-process windows, correct for the single Railway instance. **Still open:** OpenAI and Pinecone spend caps and the Railway usage limit (dashboard settings). **OPEN:** the OpenAI tokens-per-minute limit (30,000 on gpt-4.1) caused client backoff of up to ~59 s during back-to-back turns; before launch, raise the usage tier or show a "busy, try again" message.
- [x] `assistant` — P4 retrieval edge cases: send disabled on empty, explicit "no supporting passage found"  (spec `docs/superpowers/specs/2026-10-01-retrieval-edge-cases-design.md`) → **Not epic-tracked** (pre-launch triage, backlog P4) **Done 2026-10-01:** threshold 0.46 (`backend/reports/relevance-bd36247ba3f7.json`); the gate passed twice on 2026-10-01 against the demo configuration (runs `d71c6dca` and `980c4687`, `backend/reports/eval-3aabf5983b0b*.json`): over-refusal 0 of 8, answerable 100%, junk 20 of 21 (out_of_corpus 4 of 5; the one miss, `not-in-corpus`, gets a clarifying question). **Deployed 2026-10-01:** migration 0014 applied on Railway; the API rejects a blank message (422); both end-to-end tests pass on `https://ledgerlens.nknext.dev` (the approval flow, and junk never getting an answer).
- [x] `api` — P5 thumbs up/down and comment feedback, stored per guest and chat turn → **Not epic-tracked** (pre-launch triage, backlog P5) **Done 2026-10-03** (spec `docs/superpowers/specs/2026-10-02-feedback-and-document-context-design.md`, plan `docs/superpowers/plans/2026-10-02-feedback-and-document-context.md`): thumbs up/down on every recorded reply, saved on click, optional comment, latest row wins; table `chat_feedback` (migration 0015, insert-only, `GRANT INSERT` to `ledger_demo`); `POST /chat/turns/{turn_id}/feedback`; the final chat event carries `turn_id`. **Deployed 2026-10-03:** migration 0015 applied on Railway (`./script.demo.sh check`: demo role insert `t`, update `f`); live API answers 400 without a guest, 404 for an unknown turn, 422 for a bad rating; CORS preflight allows the frontend origin. The Playwright run's thumb and comment were read back from Railway with `./script.demo.sh feedback` (latest row per guest and reply: `up`, the comment, outcome `answered`, prompt `a4782adc4015`).
- [ ] `ops` — P6 Sentry on backend and frontend → **Epic 2.3** (backlog P6)
- [x] `ops` — P7 minimal usage event log: client-measured latency, outcome, feedback → **Epic 2.3** (backlog P7) **Done 2026-10-15:** client-measured TTFB per chat turn in the insert-only `chat_turn_timing` table and the `chat_usage_daily` view (migration 0016). Railway is on `0016_chat_turn_timing`, `./script.demo.sh check` passes (demo role insert `t`, update `f`), and `./script.demo.sh usage` shows TTFB rows from live chats (2026-10-07, 2026-10-12).
- [x] `frontend` — P8 document list with one-line descriptions and starter questions plus chat answer citations open the in-app viewer: "Open page →" in `Chat.tsx`'s `CitationCard` opens the PDF in a new browser tab today (only the contract profile panel uses the viewer, `91d7bbd`), so reuse the screen's `viewer` state and `DocumentViewer` (found in the deployed smoke test 2026-09-30) → **Not epic-tracked** (pre-launch triage, backlog P8) **Done 2026-10-03:** a one-line description per document (table `document_descriptions`, four rows on Railway) on the chat cards and the Documents screen; starter questions follow the selected document (`frontend/src/lib/starters.json`, each one a scoped golden case, checked by `backend/tests/test_starters_are_golden.py`); "Open page →" opens the in-app viewer. **Deployed 2026-10-03:** `frontend/e2e/demo-feedback.e2e.ts` passes on `https://ledgerlens.nknext.dev` (starter → cited answer → citation opens in the app, no new tab → thumbs-up and a comment), and so do both earlier end-to-end tests. Final gate under `5bfdd62942f4`: run `2269d5c1` 48 of 49, the one miss the known `calamos-first-tier` refusal (backlog X5), junk 21 of 21.
- [ ] `design` — compressed 4-day design sprint on P4, P5, P8, then 5-person test of the journey map → **Not epic-tracked** (pre-launch triage)
- [x] `chores` — fix the stale frontend test "reverses with a key derived from the posting id": `reversePosting` now awaits `guestHeaders()`, which first POSTs `/guests`, so `calls[0]` is the guest call, not the reversal. The test already failed before this sprint's frontend work; find the reversal call or seed a guest id → **Not epic-tracked** (found in the P1 review 2026-09-30) **Done 2026-10-02** (`1777c8a`): the test finds the reversal call by its URL.
- [ ] `ops` — at `/promote-release`: add `VITE_API_BASE` for the Vercel **Production** environment (no branch), move `ledgerlens.nknext.dev` back to Production, set the Vercel Production Branch and confirm Railway's `FRONTEND_URL` still matches; Deployment Protection was turned off for the branch build → **Not epic-tracked** (deploy note)

### Infrastructure blockers (inside P1; found 2026-09-29, each would break the public demo silently)

- [x] `ops` — **Original PDFs on ephemeral disk.** **Done 2026-09-30:** a Railway volume is mounted at `/data`, `DOCUMENT_STORE_DIR=/data/documents`, the four originals are copied in, and the API serves all four PDFs (200, `application/pdf`). `DOCUMENT_STORE_DIR` defaults to `var/documents` (`originals/<sha>`); a Railway container loses it on redeploy, breaking the viewer and every citation click. Fix: attach a Railway volume and copy the originals into it during P1. Object storage isn't needed at this scale → **Epic 1.5**
- [x] `ops` — **Separate demo Pinecone index.** **Done 2026-09-30:** `contract-demo` (1536 dims, cosine, aws us-east-1) holds the 124 vectors of the frozen corpus; the Railway service uses it. The namespace is the tenant id, the same fixed demo tenant locally and on Railway, and re-indexing deletes old vector ids, so a local re-ingest would change the live demo. Fix: give the demo its own `PINECONE_INDEX`, fill it from the frozen corpus, and never point local ingestion at it. The existing scripts (`backend/scripts/create_pinecone_index.py`, `backend/scripts/ingestion_worker.py`, `scripts/delete_pinecone_namespace.py`) read the index from `PINECONE_INDEX`, so setting it targets the demo index → **Epic 1.5**
- [x] `db` — **Roles on Railway Postgres.** **Done 2026-09-30:** `ledger_owner` and `ledger_app` created, migrations 0001 to 0012 run as `ledger_owner`, and the API reads through `ledger_app` (`/health/db` ok). With the Railway superuser, create `ledger_owner` and `ledger_app`, then run migrations as `ledger_owner`. Routine, but a step; P2 and P9 add grants on top → **Epic 1.5**
- [x] `ops` — **Build the demo locally, then ship the database.** **Done 2026-09-30:** ingested locally into `ledger_demo` with the demo keys (Tremblay 18/18 accepted, EDGAR 43 accepted and 15 needs_review), dumped without `alembic_version`, `currencies` and `tenants`, restored onto Railway as superuser; counts match (4 documents, 141 elements, 124 search rows, 18 tokens). Launch the full infra on local (a demo database + the demo Pinecone index), ingest the frozen corpus into both, then dump the demo database and restore it onto Railway. Vectors and citations reference element UUIDs, and PII tokens are HMAC'd, so Railway must run with the same `PII_HMAC_KEY` / `PII_VAULT_KEY` (Infisical) and must never be re-ingested separately. **Run these only after the local demo ingest is done** (schema already comes from `alembic upgrade head` as `ledger_owner`, so the dump is data only and skips `alembic_version` plus `currencies` and `tenants`, which migration 0004 already fills; the superuser restore with `--disable-triggers` keeps the append-only and deferred balance triggers from tripping on load order):
  ```bash
  pg_dump --data-only --exclude-table=alembic_version --exclude-table=currencies --exclude-table=tenants --disable-triggers -Fc <local-demo-db> -f demo.dump
  pg_restore --data-only --disable-triggers -d '<railway superuser public URL>' demo.dump
  ```
  Then copy the matching originals into the Railway volume, and compare row counts → **Epic 1.5**
- [x] `chores` — **Split requirements into worker and API.** **Done 2026-09-30:** `requirements.txt` is now the API set (Railway auto-installs it, image about 180 MB) and `requirements-worker.txt` adds Docling, Presidio, pytest and httpx; local work installs the worker file. `backend/requirements.txt` carries Docling and Presidio for ingestion; split into API and worker files and deploy only the API set on Railway (the worker is never hosted). `$PYDEV` locally keeps both → **Epic 1.5**
- [x] `ops` — **Separate Langfuse project for the demo.** **Done 2026-09-30:** the `demo-ledglens` project exists and the Railway service uses its keys, with `LANGFUSE_TRACING_ENVIRONMENT=demo`; the local demo ingest ran with tracing off. Keep the current Langfuse project for local work; create a new project `demo-ledglens`, and the Railway deploy uses its keys → **Epic 2.3**

### Demo-mode decisions (P2 + P9 spec, decided 2026-09-30)

What the public demo (`DEMO_MODE=1`) disables or changes, and why. Source for the guest-facing note on the demo.

- **Uploading documents is off.** The upload route is not mounted and the demo database role cannot insert into
  document tables. Why: the corpus is shared by every guest, and ingestion spends OpenAI and Pinecone money.
- **Writing to the ledger is off**: no manual postings, reversals, fee runs or GL exports; the Ledger screen hides the
  reversal button and says reversals are off in the public demo. Why: the ledger is append-only, so any public write
  would stay forever and be seen by every guest.
- **Field reviews and AI-posting approvals still work, but only for you.** Your decisions go to per-guest overlay
  tables, merged over the real data only for your session; other guests never see them. Why: a decision in the shared tables would change every other guest's answers and ledger.
- **You only see the AI proposals from your own chats.** Pending counts, approvals on the Ledger screen and the
  document timeline show the proposals your conversations produced, not other guests'. Everything else (documents,
  extracted terms, real postings) is the same shared data for everyone. Why: other guests' proposals would clutter
  your view and reveal what they asked.
- **Your decisions are final.** There is no undo, re-decide or reset for a field review or an approval, the same as
  the real system: a decision is recorded once, and in the real ledger a posting is only ever corrected by a
  compensating reversal, never by editing or deleting it (reversals are off in the demo, see above). Why: an undo
  button would teach the opposite of how the ledger works.
- **Your decisions last 24 hours of inactivity.** If you don't use the demo for 24 hours, your field reviews and
  approvals are deleted and you start from the shared data again; the cleanup runs when a new guest arrives, with no
  background job. Why: the overlays are disposable demo state, and deleting them only frees space, since nobody else
  could see them anyway.
- **An approved AI posting is checked, not recorded.** The ledger's own validation (balanced per currency, accounts
  exist and belong to the tenant, amounts positive) runs on it, and it is shown to you as "demo posting, not
  recorded". Why: the demo database role has no write access to the ledger at all. This amends the backlog's
  "rolled-back `create_posting`", which would have needed that write access.
- **Your feedback is saved, and only the operator reads it** (P5, decided 2026-10-02). Every reply has a thumbs up
  and thumbs down; a click is saved at once, and you can add a comment or change your mind (the latest counts). Known
  personal values in a comment are replaced by tokens before it is stored, the same as in a question. No other guest
  sees your feedback and no screen shows it. Why: feedback is evidence for improving the answers, not content.
- **Each document has a one-line description, and the starter questions follow the document you pick** (P8, decided
  2026-10-02). A citation's "Open page" opens the page inside the app instead of a new browser tab.

### P2 + P9 engineering decisions (settled 2026-09-30, one spec)

- **Scope:** P2 and P9 designed once for the final state; no intermediate grant on `field_reviews` that P9 would undo.
- **Milestones:** M1 code-only (unmount public writes, frontend hides them, decision routes return 403 until their
  overlay lands, the only throwaway code); M2 one migration (both overlays + `ledger_demo` grants); M3 field-review
  overlay; M4 approval overlay; M5 purge + switch Railway to `ledger_demo` + deployed smoke test.
- **Merge approach:** in Python inside each package's `dao.py`; readers take `overlay_guest: UUID | None` (None =
  today's path). Two FastAPI dependencies hold the demo-mode policy: `get_overlay_guest` for reads (no guest = shared data) and
  `require_overlay_guest` for decision writes (400 without a guest in demo mode).
  Rejected: an SQL merge function (logic split across SQL and Python, migrations for every change) and separate demo
  repositories (every reader and the approval path twice).
- **Data:** `guest_field_reviews` (PK guest, run, field) and `guest_tool_decisions` (PK guest, invocation), FKs to
  the real rows, no triggers; `ledger_demo` gets SELECT everywhere, INSERT on `guests`/`chat_turns`/`tool_invocations`,
  UPDATE (`last_seen_at`) on `guests`, INSERT + DELETE on the overlays, nothing else. Role created by hand on Railway
  and by `db_up.sh` locally; later tables the demo writes must grant INSERT explicitly.
- **Approvals:** `ledger.dao.check_posting` runs the account load and `_validate` read-only; decisions carry
  `recorded: bool`; a guest sees and decides only proposals from their own chat turns.
- **Frontend:** learns `demo_mode` from `/config`; dashboard aggregates stay cached and real, only the two pending
  counts are per guest; the Ledger reversal button is hidden.
- **Purge:** `POST /guests` deletes overlay rows of guests not seen for 24 hours; `guests` rows are kept.
- **Rollback:** `DEMO_MODE` off or `DATABASE_URL` back to `ledger_app`; the migration only adds.

### P4 engineering decisions (settled 2026-10-01, from `artifacts/research/2026-10-01-rag-edge-cases.md`)

- **Threshold:** keep one absolute cosine threshold (`MIN_DENSE_SIMILARITY`); a keyword (full-text) hit can no longer open
  the gate on its own, and below-threshold dense hits are dropped before fusion. Recalibrated with a retrieval-only script
  over answerable and junk cases: the highest value that keeps every answerable case, recorded in a report.
- **No LLM sufficiency check now.** The existing deterministic output check (answer must cite; every number must appear in
  what it cites) covers the riskiest failure; an extra model call per turn costs latency and spend. Trigger to add one: the
  eval gate failing on `out_of_corpus` or `false_premise` after the prompt rule lands.
- **Prompt rule:** state only what a cited passage or tool result explicitly says, otherwise refuse.
- **Question without a contract named (chat not scoped):** answer per contract when the corpus has the answer (at most
  four, each cited); ask one clarifying question only when the question is too vague to search (option A). Clarifying
  questions are a new `clarify` event and a `clarified` chat outcome, and may not contain numbers.
- **Refusals are explicit and system-credited:** fixed text plus a `system` citation, never the model's own wording.
- **Evaluation:** golden set gains `category` and `expect` (answer / refuse / clarify) and 20 junk cases (4 each:
  out-of-corpus, false premise, underspecified, nonsense, off-topic). Go/no-go gate (option A): zero over-refusal of
  answerables, junk acceptable rate at least 90% overall and at least 75% per category. `eval_config_hash` gains the
  threshold. Calibration and eval run against the live demo configuration.
- **Not adopted:** a pre-retrieval classifier and a reranker (no evidence they are needed at four contracts).
- **Decided after the first gate run (2026-10-01, spec D9–D16):**
  - **Fixed clarifying text:** the model only decides to ask; the service writes the question from the indexed contract
    titles (this replaces "may not contain numbers" above: the model's text is discarded).
  - **Absence claims are rejected by the output check:** "does not charge X", "there is no X" fail unless a cited source
    says the same words (a pattern list; the LLM sufficiency check stays the upgrade path).
  - **History is context, never a source:** every fact comes from a tool call in the current turn, so a repeated question
    is answered again, not refused.
  - **Nonsense accepts a clarification** as well as a refusal; the keyword-only nonsense case is real nonsense.
  - **Eval runs are isolated and paced:** fresh session ids per run (earlier runs' turns were being fed back as history),
    a pause between cases, one retry after a provider error.

### P5 + P8 engineering decisions (settled 2026-10-02, one spec)

Input: `artifacts/pre-launch-demo-design-sprint.md` (local) is a plan with no test results yet; it supplies the journey
steps to pass (2, 3, 5, 8) and the "feedback in under 30 seconds" target.

- **Feedback rows are append-only, latest wins.** Table `chat_feedback`: each thumb click or comment inserts a row that
  carries the rating; readers take the latest per guest and turn. `ledger_demo` gets an explicit INSERT and nothing else.
- **Prompt version is not copied:** the feedback row references the chat turn, which is immutable and already holds
  prompt, model and graph version.
- **Feedback on every recorded reply:** answers, refusals and clarifying questions. Client errors and rate-limit
  messages have no turn, so no control.
- **The final chat event carries `turn_id`** so the browser can address the turn.
- **Abuse bound without a second limiter:** the turn must belong to the guest (404 otherwise), and at most 5 feedback
  rows per guest and turn (429).
- **Comments are tokenised** with the known-value tokeniser before storage, capped at 1000 characters.
- **Read by the operator with SQL only:** no read endpoint and no dashboard count; P7 joins the table by chat turn.
- **Descriptions live in a separate insert-only table** `document_descriptions`, filled by the migration by
  `document_key`. A column on `documents` was rejected: its append-only trigger blocks the UPDATE needed to fill it.
- **Starter questions follow the selected document:** a frontend constant keyed by `document_key`; four across the
  documents when none is selected. Every starter is an answerable `"retrieval": true` case in `tests/eval/golden.json`.
- **Citations carry `document_id`** so "Open page" opens the in-app viewer the chat screen already has.
- **Not adopted:** the end-of-chat feedback prompt (optional in the backlog).
- **Operator runbook:** the migration's Railway steps go in both `backend/script.demo.md` (raw queries) and
  `backend/script.demo.sh` (subcommands); both stay local.

### Answer-reliability findings from the starter pre-check (2026-10-02, fixed before P5 + P8 was built)

Asking the new starter questions locally against the demo configuration showed that answerable questions were being
refused some of the time. The P4 gate missed it: it asked each question once and never scoped to a document. Three
causes were traced with the tool calls and the verification results logged, and fixed:

- **Derived numbers in the tool output** (`d912986`). The contract-fields tool gave the model `rate_bps`; the model
  sometimes wrote "0.55% (55 basis points)"; no cited source contains "55", so the output check rejected the answer and
  the retry refused. The tool now sends only `rate_text` and `band_text`. Fee-schedule questions scoped to a document
  were refused in 1 to 3 of 4 attempts before.
- **Terse search queries under the relevance floor** (`cd6641b`). The agent rewrites a question into keywords ("fees",
  "fee calculation"), which score 0.31 to 0.39 against a document whose passages score 0.68 for the full question; the
  0.46 floor was calibrated on full questions, so the search returned nothing. Search now keeps a passage that is
  relevant to the model's query or to the guest's own question. Junk questions still score under the floor.
- **List numbering read as figures** (`f4bfa4f`, `d992d22`). Once every contract returned passages, "What is the
  management fee?" was answered as a numbered list and the check rejected the markers 2, 3 and 4. Decision: a
  multi-contract answer is a list of per-contract sections (a schema field), each checked against its own citations
  only; the service adds each contract's title as the heading. If a section still fails after the retry, the verified
  sections are answered and the failing one is dropped. Before this, the P4 runs passed that case on an answer covering
  one contract of four.
- **Eval harness** (`5b84509`): cases marked `"scoped": true` are asked a second time limited to their document; the
  12 starter questions are golden cases (37 cases, 49 questions per run).
- **Result under configuration `5bfdd62942f4`** (the answer prompt changed, so the hash did): run `5683f35b` 48 of 49
  (one refusal), run `267ae961` 49 of 49 with junk 21 of 21. Reports: `backend/reports/eval-5bfdd62942f4*.json`.
- **Known and accepted (decided 2026-10-02):** an answerable question is still refused occasionally. In run `5683f35b`
  it was `calamos-first-tier`, asked with no document selected; the same question was answered 10 of 10 when traced, so
  the cause is not known. No more tuning before real guests use the demo; P5 feedback and P7's usage log will show how
  often it happens. The gate's zero-refusal rule therefore fails on some runs.
- **Also seen:** the OpenAI account ran out of credits during a gate run (every turn then ends in `error`). The spend
  cap and balance alert in P3 are still open.


### Deferred

- [ ] `ops` — P6 Sentry on backend and frontend: the code is merged and reports only when `SENTRY_DSN` / `VITE_SENTRY_DSN` are set; not yet verified on the deployed demo → **Epic 2.3** (backlog P6)
- [ ] `api` — P3 remainder: OpenAI and Pinecone spend caps, the Railway usage limit, and the OpenAI tokens-per-minute backoff (raise the tier or show "busy, try again") → **Not epic-tracked** (backlog P3)
- [ ] `design` — compressed 4-day design sprint on P4, P5, P8, then 5-person test of the journey map → **Not epic-tracked** (pre-launch triage)
- [ ] `ops` — Vercel Production switch at `/promote-release` (see the scope item above) → **Not epic-tracked** (deploy note)

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
