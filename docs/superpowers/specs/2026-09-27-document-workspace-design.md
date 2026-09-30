# Document workspace — design (Phase 2 of the demo-ready sprint)

**Date:** 2026-09-27 · **Branch:** `feat/demo-ready` · **Backlog:** "Demo-ready sprint — fintech reframing",
items N19, N12, N17, N11, N13, N14 · **Implementer:** Gemini, from the implementation plan · **Reviewer:** Claude

## 1. Goal and success

A user picks an ingested contract and, in one screen, sees what the system knows about it and what it did
with it: its terms with their review status (N17), the facts the agent could not confirm (N11), the AI calls
behind each answer (N13) and the ledger entries that resulted (N14), while chatting about it, optionally
scoped to that one document (N12). Audience: wealth / asset management compliance and operations.

Success is decided in Phase 4: the demo script (N15) walks through all of it on one document without leaving
the flow, and the live run's result decides `/end-sprint`. Phase 3 (copy) runs right after this phase.

**Constraints:** no user accounts (single tenant, guests only); panels are read-only (approvals keep using the
existing approval / review flow); no new npm package; every new Python dependency goes in
`backend/requirements.txt` (none expected); CLAUDE.md layering: thin routes, DB access only in each package's
`dao.py`, dependencies point toward `ledger`.

**Working labels** come from the reframing glossary ("Current → Target" table in
`artifacts/research/2026-09-26-reframing-metrics-regulatory-output.md`): "Audit trail", "Awaiting review",
"Billing reconciliation", "Every number traced to its source page". Phase 3 polishes wording, it doesn't rename.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Where the experience lives | **Chat-centred (layout A):** document cards above the chat, collapsing to a scope chip on the first question; a right panel with tabs Profile · Audit trail · Ledger; a side sheet on narrow screens | The demo moment needs the question, the unconfirmed field and the tool call visible together |
| Backend shape | **One endpoint per panel**; the timeline is a read model in `reporting` | Panels load and fail independently; one owning package per endpoint; no god endpoint; no domain logic in React |
| Identity | **Guests (N19)**: a `guests` table, id in `localStorage`, sent as `X-Guest-Id` | Attribution for chats and decisions, a key for the public demo's rate limit, an upgrade path to real users. **Attribution, not authentication** — a guest id never grants access |
| Guest vs conversation | A guest (browser) has many conversations (`ses_xxxxxxxx`, as today) | Different lifetimes, different concepts |
| Scoping | Enforced **in the tools**, not in the prompt | The model can't escape the scope; prompt, `prompt_version` and golden set unchanged |
| Unvalidated fields (case 1) | A fixed-template notice from a new SSE event, not model text | Verifier and prompt untouched; same data as the Profile tab |
| Not comparable (case 2) | **Option A** (decided 2026-09-27): the tool's reason as a fixed message with a `system` citation | Recorded in the backlog; research: `artifacts/research/2026-09-27-flagged-items-framing.md` (conclusions only) |
| Audit freshness | Refetch after each turn **plus a refresh button** (top corner of the Audit trail and Ledger tabs) | Live streaming is deferred: backlog **D6** (Postgres trigger → `NOTIFY` → FastAPI `LISTEN` → SSE), part of the deferred agentic-depth work |

## 3. Backend

### 3.1 N19 — guests (package `app/assistant`)

- Migration `0012_guests_and_turn_scope`: table `guests(id uuid pk default gen_random_uuid(), tenant_id uuid not
  null references tenants, created_at timestamptz not null default now(), last_seen_at timestamptz not null
  default now())`; `chat_turns.guest_id uuid null references guests(id)`; `chat_turns.document_id uuid null
  references documents(id)` (N12).
- Grants: `ledger_app` gets `SELECT, INSERT` on `guests` and `UPDATE (last_seen_at)` only. This is the first
  UPDATE grant outside the append-only tables, deliberately limited to one column.
- `POST /guests` → `201 {"id": "<uuid>"}`.
- Resolving a guest (`X-Guest-Id` header, a FastAPI dependency in `app/deps.py`): a valid, known id updates
  `last_seen_at` and is recorded; a missing, malformed or unknown id resolves to `None` — never an error.
- `decided_by` on review decisions (`routes/reviews.py`) and tool-invocation decisions
  (`routes/tool_invocations.py`) becomes `"guest:<first 8 chars of the id>"` when a guest resolves, else the
  existing `DECIDED_BY` constant (`app/deps.py`).

### 3.2 N12 — scoped chat (packages `app/assistant`, route `routes/chat.py`)

- `ChatIn` gains `document_id: uuid.UUID | None = None` (backward compatible).
- `/chat` with a `document_id` that doesn't exist for the tenant → `404` problem response before any model call.
- `ToolContext` gains `document_id: uuid.UUID | None`. When set:
  - `list_documents` returns only that document;
  - `search_contracts` always searches `[document_id]` whatever `document_ids` the model passes;
  - `get_contract_fields` and `compare_contract_to_billing` called with a different id return the tool error
    `{"error": "This chat is scoped to <title>."}`.
- The turn row stores `document_id` and `guest_id`.

### 3.3 N17 — `GET /documents/{id}/terms` (package `app/contracts`)

Response (latest extraction run of the current version):

```json
{
  "document_id": "…", "title": "…",
  "extraction": null | {
    "run_id": "…", "extracted_at": "…",
    "fields": [{
      "path": "fee_method", "label": "Fee method", "group": "fee_schedule",
      "value": …,
      "status": "accepted" | "confirmed" | "corrected" | "needs_review",
      "reason": null | "not grounded in the cited text" | "<validator error>" | "low page quality (<grade>)",
      "citations": [{"element_id": "…", "page": 3, "quote": "…"}]
    }]
  },
  "household": null | {"id": "…", "name": "…"},
  "billing_schedule": null | {"version": 2, "method": "graduated", "tiers": [...], "valid_from": "…"},
  "coming_soon": ["fee_schedule_history", "client_type", "exceptions", "referral_arrangements", "expense_allocation"]
}
```

- Groups: `parties` (fund_or_account, adviser, client, signatories), `fee_schedule` (fee_basis, fee_method,
  currency, fee_bands), `billing_terms` (billing_frequency, payment_timing), `term_and_law` (agreement_date,
  effective_date, termination_notice_days, governing_law).
- Status and value come from the **same logic as `served_fields`** (corrected value wins; confirmed or
  auto-accepted is served; everything else is `needs_review`) — one definition of "served", reused, not copied.
- `reason` is derived from `grounded`, `validator_errors`, `page_grade`, in that order of precedence.
- `404` for an unknown document; `extraction: null` when not extracted yet; `household`/`billing_schedule`
  `null` when the document has no household or no schedule in effect today.
- Quotes are tokenised in storage; the route reveals them for display exactly like `GET /documents/{id}` does.

### 3.4 N11 — unvalidated fields and the not-comparable notice (package `app/assistant`, eval harness)

- `ToolOutcome` gains `not_validated: list[str]` (field paths), filled by `get_contract_fields` from
  `served.unserved`, and `system_notice: str | None`, filled by `compare_contract_to_billing` when it catches
  `ContractNotComparable` (the exception's reason).
- The service collects both across the turn (graph state).
- **Case 1:** if any `not_validated` were collected, the stream sends
  `unvalidated {document_id, title, fields: [{path, label, reason}]}` **before** `answer`/`refused`.
- **Case 2:** if the turn ends refused and a `system_notice` exists, the stream sends `refused` with the
  notice's fixed text and one citation `{"kind": "system", "source": "billing records", "detail": <reason>}`
  instead of the generic refusal text.
- Eval (`backend/tests/eval/golden.json`, `test_golden.py`): `fund-not-comparable` gets
  `"expect_system_notice": true`; the harness counts it as a refusal-ok and citation hit only when a `system`
  citation carrying the expected reason is present. No other case changes.

### 3.5 N13 — `GET /tool-invocations?session_id=…` (route `routes/tool_invocations.py`)

- Optional `session_id` filter on the existing list; response unchanged, plus `trace_id` per invocation
  (joined from `chat_turns` of the same session, nearest turn at or after the call; `null` when tracing was off).

### 3.6 N14 — `GET /documents/{id}/timeline` (package `app/reporting`, new `reporting/timeline.py` + dao query)

- Items `{at, kind, title, detail, links}`, `kind ∈ ingested | extracted | reviewed | ai_proposed | decided | posted`,
  sorted by `at` ascending. Sources:
  - `version_events` of the document's versions → `ingested` (one item per completed stage);
  - `extraction_runs` → `extracted` (accepted / awaiting-review counts); `field_reviews` → `reviewed`;
  - `tool_invocations` with `input->>'document_id' = :id` → `ai_proposed` (amount, currency, tool);
  - their `tool_invocation_decisions` → `decided`; decisions with a `posting_id` → `posted` with the posting's
    entries (account name, direction, amount in minor units, currency).
- `404` for an unknown document; empty list when nothing happened yet. Read-only: no writes.
- `# ponytail:` the JSONB filter scans `tool_invocations` (a few hundred rows, one tenant); add an expression
  index on `(tenant_id, (input->>'document_id'))` when volume grows.
- The ordering/merging is a pure function (`build_timeline(rows) -> list[TimelineItem]`), tested without the DB.

## 4. Frontend (React + TypeScript, no new package)

- `api.ts`: `guestId()` — `POST /guests` once, id in `localStorage` (try/catch; memory fallback when storage is
  blocked); `X-Guest-Id` on `/chat` and on review / approval decisions; `streamChat` takes an optional
  `documentId`; typed clients for `/terms`, `/timeline`, `/tool-invocations?session_id=`.
- `screens/Chat.tsx` becomes the layout shell; new components under `components/workspace/`:
  - `DocumentCards` — ingested documents as cards (title, pages, status, awaiting-review count) above the input;
    click selects, click again clears; `/chat?document=<id>` preselects.
  - `ScopeChip` — after the first question the cards collapse to "Scoped to: <title> ✕" / "All documents";
    click reopens the cards. Changing scope starts a new conversation (new session id).
  - `DocumentPanel` — right panel, accessible tabs (`role="tablist"`, arrow keys): **Profile**, **Audit trail**,
    **Ledger**. No document selected → only **Audit trail**. Narrow screens → side sheet opened from the chip
    (reuse the Documents sheet pattern).
  - `ContractProfile` (N17) — field groups; each field: value, status badge, citation chip opening the PDF
    viewer on its page, reason when awaiting review; household + billing schedule in effect beside the fee
    bands; **coming-soon slots greyed out** with a "Coming soon" badge, `aria-disabled`, not interactive.
  - `AuditLog` (N13) — this session's tool calls, newest first: tool, time, inputs, model, prompt version,
    decision, posting / approval links, "View trace" when a `trace_id` exists. Refetches after each `done`
    event **and has a refresh button in its top corner**.
  - `LedgerTimeline` (N14) — vertical timeline ingested → extracted → reviewed → AI proposed → decided →
    posted; posting items expand to their debit/credit entries in CAD; link to `/ledger?posting=…`.
    Refetches after an approval **and has the same refresh button**.
  - `UnvalidatedNotice` (N11) — under the answer: "Not confirmed, awaiting review: <labels> → Review".
  - The citation chip renders `kind: "system"` as "System · billing records".
- `screens/Documents.tsx`: an "Ask about this document" button in the detail pane → `/chat?document=<id>`.
- Every tab: loading, empty ("No AI decisions in this conversation yet", "Not extracted yet") and error
  states; a failing tab never blocks the chat. Props interfaces on every component, no `any`.

## 5. Testing

Backend (pytest, the real `ledger_test` database, no network; fast suite plus `-m slow`):

- N19: `POST /guests` creates a row; `/chat` with a known guest records `guest_id` and moves `last_seen_at`;
  unknown / malformed / missing → `NULL`, no error; decisions with the header record `guest:<8 chars>`.
- N12: scoped search returns only that document's elements even when the model passes other ids; a contract
  tool with another id returns the scope error; unknown `document_id` → 404; unscoped chat unchanged
  (existing tests pass untouched).
- N17: each status (accepted, confirmed, corrected, needs_review + reason); household + schedule in effect;
  `null`s without household / schedule; not extracted yet; 404.
- N11: pending fields → one `unvalidated` event before `answer`; not comparable → fixed notice with a
  `system` citation, never the generic refusal; harness rule for `expect_system_notice` unit-tested without
  OpenAI.
- N13: `session_id` filter returns only that session's calls.
- N14: `build_timeline` ordering and kinds as a pure-function test; one DB test through ingest → extract →
  review → proposal → approval → posting; another document's items never appear.

Frontend: `npm run build` passes (TypeScript, `noUnusedLocals`); a Playwright walk-through of the Phase 4
flow: select a card → ask → notice + audit + ledger update → approve → refresh → timeline shows the posting.

## 6. Build order (one commit per logical change; Claude reviews after each step)

1. N19 guests + migration `0012_guests_and_turn_scope` (also `chat_turns.document_id`)
2. N12 scoped chat — backend, then cards, chip and panel shell
3. N17 `/terms` + Profile tab
4. N11 `unvalidated` event, system notice, eval rule + notice UI
5. N13 session filter + Audit trail tab (with refresh)
6. N14 `/timeline` + Ledger tab (with refresh) + "Ask about this document"

## 7. Out of scope

Live audit streaming (D6, deferred agentic depth), domain metrics (D8), new clause types (D14), fee schedule
version history (D15), copy polish (Phase 3), re-ingestion and the live tracing run (Phase 4), authentication.

## 8. Skills that informed the design

- **clean-architecture** — thin routes; the timeline as a read model in `reporting`; dependencies toward `ledger`.
- **domain-driven-design** — guest ≠ conversation; the glossary as ubiquitous language.
- **ddia-systems** — foreign keys for `guest_id` / `document_id`; the JSONB scan ceiling stated with its fix.
- **pragmatic-programmer** — one definition of "served" (DRY); scope enforced in the tools (contracts at the boundary).
- **clean-code** — focused components and pure functions; tests on every failure path.
- **supabase-postgres-best-practices** — least-privilege grants (column-level UPDATE); an index plan.
