# Fintech Ledger + Document Intelligence — Changelog

All notable changes to this project are documented in this file.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

Pre-2026-08-31 history belongs to this repo's original ML/hackathon project
(topic classification, model deployment pipeline) — a different product, not
carried forward. This changelog starts at the restart into the current
Fintech Ledger + Document Intelligence product.

---

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

## [Restart] — 2026-08-31

Repo restarted as Fintech Ledger + Document Intelligence — a double-entry
ledger core paired with a document-intelligence chat feature, replacing the
prior ML/hackathon project in this repository.
