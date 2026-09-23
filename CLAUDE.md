# Fintech Ledger + Document Intelligence — Claude Code Project Context

## Project in One Sentence
A double-entry ledger core (idempotent postings, balance-invariant enforcement,
compensating reversals) paired with a document-intelligence chat feature (OCR
ingestion, retrieval-augmented Q&A with citations, agentic tool-calls back into
the ledger).

## Repository Structure
```
fintech-prod/
├── backend/          # Python 3.11 / FastAPI
│   ├── app/
│   │   ├── ledger/   # models, DAO, DB session — double-entry core
│   │   └── routes/   # FastAPI routers
│   ├── alembic/      # migrations
│   ├── scripts/      # db_up.sh — idempotent local Postgres setup
│   └── tests/        # pytest
├── frontend/         # React (Vite) + TypeScript
├── docs/superpowers/ # brainstorming specs + writing-plans implementation plans
├── artifacts/        # product-backlog.md — full phased scope, epic-numbered
├── graphify-out/     # knowledge graph of this repo — see graphify section below
└── .claude/          # this folder
```

## Tech Stack (locked — see `artifacts/product-backlog.md` for full rationale, do not suggest alternatives)
| Layer | Choice |
|---|---|
| Backend | Python 3.11 + FastAPI |
| Frontend | React (Vite), no framework beyond React itself |
| DB | PostgreSQL 18 + pgvector — localhost for dev (roles: ledger_owner migrates, ledger_app runs the API with SELECT/INSERT only), Aurora PostgreSQL for the demo/deploy run (verify 18 support before Epic 1.5) |
| OCR | AWS Textract, synchronous API (AnalyzeDocument) |
| LLM gateway | LiteLLM |
| Migrations | Alembic |
| Testing | pytest; concurrency stress test via `asyncio` + `httpx.AsyncClient` |
| Transport between ledger/document phases | none — in-process calls, no gRPC/internal API |
| Transport security | HTTPS/TLS everywhere this is deployed, no exception for the demo |

## Current Scope
**Done:** ledger DB core — schema/migrations (Epic 1.1), balance-invariant deferred constraint trigger (Epic 1.2), DB session factory, DAO + tests, `db_up.sh` local Postgres setup, `POST /postings` (Epic 1.3), concurrency stress test (Epic 1.4), append-only ledger enforced by triggers + revoked privileges, reversals (Epic 1.7), household fee billing on versioned schedules, AI tool-invocation governance tables, GL-ready export.

**Not yet built:** Aurora deployment (Epic 1.5), README numbers (Epic 1.6), Week 2 iteration, Document Intelligence Chat (Iteration 3).

Full phased scope, ordering rationale, and Icebox: `artifacts/product-backlog.md`.
Design specs and implementation plans: `docs/superpowers/specs/`, `docs/superpowers/plans/`.

**Before starting new work:** check `artifacts/product-backlog.md` for the
next unchecked epic and `docs/superpowers/plans/` for whether it already has
an approved plan — don't re-litigate scope that's already decided there.

## Code Conventions
- **Python:** type hints on every function signature (already the norm in
  `app/ledger/`); dataclasses for input DTOs (see `EntryInput` in `dao.py`),
  not raw dicts; SQLAlchemy 2.0 session semantics — do not call `session.begin()`
  explicitly, sessions autobegin (see the comment in `create_posting()` for why
  this matters for the deferred-trigger transaction boundary).
- **TypeScript:** no explicit `strict` flag is set in `tsconfig.app.json` yet
  (`noUnusedLocals`/`noUnusedParameters` are) — don't rely on that gap, still
  avoid `any` and define prop interfaces for every component regardless.
- **Layering:** routes stay thin (parse request → call a `ledger` module
  function → return) — no business logic in `app/routes/`, no direct DB
  access outside `app/ledger/dao.py`. This is a two-file pattern today
  (`models.py`/`dao.py`); keep new domain logic in that module, not in routes.
- No new Python dependency without adding it to `backend/requirements.txt`.
  No new npm package without noting it in the task/PR summary.

## Running Locally

### Backend
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest
.venv/bin/pytest -m stress
.venv/bin/python scripts/seed_demo.py
```
Prerequisite: `./backend/scripts/db_up.sh` (idempotent — Docker Postgres 16,
creates `ledger_dev`/`ledger_test`, runs migrations against both).

### Frontend
```bash
cd frontend && npm install && npm run dev
```

## Branch Strategy & Sprint Lifecycle
- Feature branches: `type/short-description` (`feat`|`fix`|`chore`|`refactor`|`docs`|`test`).
- `preview` is the starting point for all new work — cut every feature/fix/chore
  branch from `preview`, never from `main`.
- `main` is production-ready only — nothing lands there except a promoted
  release from `preview`.
- Feature branches merge into `preview` via PR (`/end-sprint`).
- Once merged into `preview`, no local sync step is needed for the next
  branch — cut it from `preview` directly.
- When `preview` is ready to ship, promote it to `main` via `/promote-release`.
- Both `main` and `preview` are protected — never commit directly to either.

```
/start-sprint <short-description>   ← branches from preview, seeds CHANGELOG.md scope
  work the sprint's scope, one commit per logical change
  /audit [package|epic]             ← anytime, sanity-check what's actually done
/end-sprint                         ← pushes, opens PR to preview, merges if clean
  ...repeat for the next sprint, cut from the now-current preview...
/promote-release                    ← when preview is ready to ship: PR + merge to main
```

**CHANGELOG convention:** every `### Completed`/`### Deferred` line links to its
backlog epic where one exists — `→ **Epic N.M**` — cross-referencing
`artifacts/product-backlog.md`. If the work has no corresponding epic (e.g.
exploratory design work outside the epic-numbered scope), say so explicitly
(`**Not epic-tracked**`) rather than omitting the link silently or inventing
an epic number.

## Git Rules
- **Never add Claude (or any AI assistant) as a co-author on commits.** Hard
  rule, shared across every repo — not project-specific.
- Commit style: conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- Never commit directly to `main` or `preview` — check first: `git branch --show-current`.
  If it's either, stop and create a feature branch before staging anything.
- Stage files explicitly (`git add <f1> <f2> ...`) — never `git add -A` or `git add .`.
  Review `git status`/`git diff --staged --stat` before committing.
- One commit per logical change, not per file — all files belonging to the
  same change are staged and committed together.
- Never hardcode secrets; never commit `backend/.env` (already gitignored) or
  anything matching `.gitignore`.
- If `git status` shows unexpected files outside what you meant to change,
  stop and report before committing.

## Custom Commands
- `/start-sprint <short-description>` — cut a feature branch from `preview`,
  push it, seed `CHANGELOG.md` with the sprint's scope as the first commit.
- `/end-sprint` — push the current branch, open a PR against `preview`,
  verify it's actually mergeable, merge if clean, sync local `preview`.
- `/promote-release` — promote `preview` → `main` via PR once `preview` is
  ready to ship; same mergeability rigor as `/end-sprint`.
- `/audit [backend|frontend|"Epic N.M"]` — read-only status check: what's
  done, partial, or not started, cross-referenced against
  `artifacts/product-backlog.md` and `CHANGELOG.md`. Never modifies files.

## Before Big Tasks
For any task that spans more than one file or changes an API contract:
1. Write a short plan (what you'll change, what you won't touch, any open questions)
2. Wait for explicit approval before implementing
3. After implementing, summarize what changed and flag any deviations from the plan

## Key Files to Read First
- `artifacts/product-backlog.md` — phased scope, epic ordering, Icebox
- `docs/superpowers/specs/` — design specs for what's already been decided
- `docs/superpowers/plans/` — implementation plans for in-progress/completed epics
- `backend/app/ledger/models.py` and `dao.py` — the ledger core's actual shape

## graphify

This project has a knowledge graph at `graphify-out/` (308 nodes, 468 edges,
21 communities as of the last build) covering code, docs, and the UI-research
mockups.

Rules:
- For codebase questions, first run `graphify query "<question>"` when
  `graphify-out/graph.json` exists. Use `graphify path "<A>" "<B>"` for
  relationships and `graphify explain "<concept>"` for focused concepts.
  These return a scoped subgraph, usually much smaller than
  `GRAPH_REPORT.md` or raw grep output.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or
  when query/path/explain don't surface enough context.
- After modifying code, run `graphify update .` to keep the graph current
  (AST-only for code changes, no LLM cost).
- `.graphifyignore` excludes `docs/superpowers/`, `.claude/commands/`,
  `.claude/worktrees/`, `frontend/public/`, and the discarded UI-research
  screenshots (`artifacts/ui-research/screenshots/`) — the shipped-mockup
  images in `artifacts/ui-research/stitch/` are in scope.
