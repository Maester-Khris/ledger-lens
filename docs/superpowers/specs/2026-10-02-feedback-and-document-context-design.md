# Answer Feedback and Document Context (P5 + P8) — Design

**Date:** 2026-10-02 · **Branch:** `feat/pre-launch-demo` · **Backlog:** P5 and P8 (pre-launch sprint) · **Not epic-tracked**
**Status:** approved in brainstorming 2026-10-02, pending written-spec review.
**Input:** `artifacts/pre-launch-demo-design-sprint.md` (local, untracked). It is a plan with an empty results grid, so
it supplies targets, not evidence. Section numbers (§) below refer to this spec.

## 1. Purpose

The public demo must show evidence of real use, and a first-time guest must reach a cited answer unaided.

- **P5:** a guest can rate any reply and optionally say why. Today nothing records what a guest thought of an answer.
- **P8:** a guest can tell what the four documents are and has a question to click. Today the document cards show a
  title, page count and version only; the four starter questions never change, so a guest who selected the Calamos
  document is offered Tremblay questions; and a citation's "Open page →" leaves the app for a new browser tab.

Journey steps this must pass (design-sprint file): 2 (reads the document list), 3 (starts within 30 seconds),
5 (clicks a citation and lands on the right page), 8 (leaves feedback in under 30 seconds).

## 2. Success criteria

1. Every recorded reply (answer, refusal, clarifying question) shows a thumbs up and a thumbs down. One click stores a
   row; no second action is needed.
2. After a click, the guest can add a comment or pick the other thumb; each stores a new row, and the latest row per
   guest and turn is the guest's feedback.
3. A stored comment has known personal values replaced by tokens, the same as a stored question.
4. Connected as `ledger_demo`: INSERT into `chat_feedback` succeeds; UPDATE and DELETE fail with `permission denied`.
5. Feedback for a turn that does not exist or belongs to another guest answers 404; a sixth row for one guest and turn
   answers 429; a request without a guest answers 400.
6. `GET /documents` returns `description` for each of the four demo documents; the chat cards and the Documents screen
   show it.
7. With no document selected the chat shows four starters, one per document; with one selected it shows that
   document's three. Every starter string is an answerable `"retrieval": true` case in `tests/eval/golden.json`, and
   the eval gate passes twice with them.
8. "Open page" on a chat citation opens the in-app viewer on the cited page; no new tab opens.
9. Every existing test passes; the normal suite makes no LLM call.

## 3. Decisions (settled 2026-10-02)

| # | Decision | Why |
|---|---|---|
| D1 | Feedback is append-only; the latest row per guest and turn wins. | The thumb survives a guest who never comments; the demo role needs INSERT only. |
| D2 | Every feedback row carries the rating; a comment row repeats it. | The latest row is complete on its own; no reader has to merge rows. |
| D3 | Prompt version is read through the turn, not copied. | `chat_turns` rows are immutable and hold prompt, model and graph version. |
| D4 | The control appears on every recorded reply, not on client errors or 429 messages. | Thumbs-down on refusals is the backlog's counter-metric; errors have no turn. |
| D5 | The final chat event carries `turn_id`. | The browser has no other way to address a turn. |
| D6 | Abuse bound: turn must belong to the guest; at most 5 rows per guest and turn. | Chat is already capped at 10 turns per 10 minutes, so no second limiter is needed. |
| D7 | Comments are tokenised and capped at 1000 characters. | Same privacy boundary as questions. |
| D8 | No read endpoint and no dashboard count; the operator reads by SQL. | Nothing guest-written is exposed; P7 joins this table by turn later. |
| D9 | Descriptions live in `document_descriptions`, insert-only, filled by the migration. | `documents` has an append-only trigger that blocks the UPDATE a new column would need. |
| D10 | Starters are a frontend constant keyed by `document_key`. | They are UI copy tied to the eval set, not data. |
| D11 | Element citations carry `document_id`. | The viewer needs it; parsing it out of `file_url` would be fragile. |
| D12 | No end-of-chat feedback prompt. | Optional in the backlog; revisit only if fewer than 2 of 5 testers give feedback. |
| D13 | Railway steps go in both `backend/script.demo.md` and `backend/script.demo.sh`. | The operator runbook must match the schema (both files are local, never committed). |

## 4. Data model — migration `0015_feedback_descriptions`

```sql
CREATE TYPE feedback_rating AS ENUM ('up', 'down');

CREATE TABLE chat_feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  turn_id uuid NOT NULL REFERENCES chat_turns(id),
  guest_id uuid NOT NULL REFERENCES guests(id),
  rating feedback_rating NOT NULL,
  comment_redacted text NULL CONSTRAINT ck_chat_feedback_comment_length CHECK (char_length(comment_redacted) <= 1000),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_chat_feedback_turn ON chat_feedback (turn_id, created_at DESC);
GRANT INSERT ON chat_feedback TO ledger_demo;

CREATE TABLE document_descriptions (
  document_id uuid PRIMARY KEY REFERENCES documents(id),
  description text NOT NULL CONSTRAINT ck_document_descriptions_length CHECK (char_length(description) BETWEEN 1 AND 200),
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO document_descriptions (document_id, description)
SELECT d.id, v.description FROM documents d JOIN (VALUES ...) AS v(document_key, description) USING (document_key);
```

- `ledger_app` gets SELECT and INSERT on both tables from migration 0003's default privileges; `ledger_demo` gets
  SELECT from 0013's default privileges and the explicit INSERT above. Nobody gets UPDATE or DELETE.
- No append-only triggers: the privileges already prevent change, as with the guest overlays.
- The description insert joins on `document_key`, so a database without those documents (a fresh `ledger_test`) gets
  no rows and the migration still succeeds.
- Downgrade drops both tables and the enum.

**Descriptions (draft, edit freely):**

| `document_key` | Description |
|---|---|
| `tremblay-ima` | Synthetic household agreement: a graduated advisory fee in CAD, billed quarterly. The only contract with billing records to compare against. |
| `calamos-emerging-market-equity` | Notice amending a fund management agreement: an eight-tier fee on average daily net assets, down to 0.90% above $26 billion. |
| `aim-global-trends-advisory` | Master advisory agreement from 2001: a four-tier fee starting at 0.975%, with a 60-day termination notice. |
| `nomura-tax-free-colorado-ima` | 2025 management agreement for the Nomura Tax-Free Colorado Fund: a four-tier fee starting at 0.55%, paid monthly. |

## 5. Backend

### 5.1 Feedback (`app/assistant`)

- `models.py`: `FeedbackRating` enum and `ChatFeedback`.
- `dao.py`: `find_turn(session, tenant_id, turn_id)`, `count_feedback(session, guest_id, turn_id)`,
  `add_feedback(session, ChatFeedback)`.
- `feedback.py` (new): `record_feedback(session, FeedbackInput, hmac_key, vault_key) -> uuid.UUID`, with
  `FeedbackInput` a dataclass (`tenant_id`, `guest_id`, `turn_id`, `rating`, `comment`). It:
  1. raises `TurnNotFound` when the turn is missing or `turn.guest_id != guest_id`;
  2. raises `FeedbackLimitReached` when `count_feedback >= 5` (constant `MAX_FEEDBACK_PER_TURN`);
  3. tokenises a non-empty comment with `documents_dao.tokenize_known_values`; a blank comment is stored as NULL;
  4. inserts and commits.
- `app/errors.py`: `TurnNotFound` → 404, `FeedbackLimitReached` → 429, through the existing `DomainError` mapping.
- `routes/chat.py`: `POST /chat/turns/{turn_id}/feedback`, body `{rating: "up" | "down", comment?: string ≤ 1000}`
  (`extra="forbid"`), answering 201 `{id}`. A missing guest answers 400. The route only parses and calls
  `record_feedback`. It is mounted in demo mode (the chat router already is).

Timing: `run_turn` saves the turn row after it yields the final event. A click that beats the commit gets 404 and the
control offers a retry; no server-side wait.

### 5.2 Turn id in the stream

`run_turn` adds `"turn_id": str(turn_id)` to the data of every final event it yields (`answer`, `refused`, `clarify`,
including the timeout refusal). `progress`, `unvalidated` and `error` are unchanged.

Readers to update and test: `ChatEvent` and `streamChat` (frontend), `Chat.tsx`'s `Turn`, and
`tests/eval/test_golden.py` (reads only `text` and `citations`; verify it still passes).

### 5.3 Descriptions (`app/documents`)

- `models.py`: `DocumentDescription`.
- `dao.py`: the document list and detail queries left-join `document_descriptions`.
- `routes/documents.py`: the summary response gains `description: str | None`.

Readers: `DocumentSummary` in `frontend/src/api.ts`, used by Chat, Documents and Dashboard.

### 5.4 Citations

`assistant/tools.py` and `assistant/contract_tools.py` add `"document_id"` to each citation they build that has a
`file_url`. Additive: stored citations of older turns lack it and are never reopened in the viewer.

## 6. Frontend

- **`components/FeedbackControl.tsx` (new).** Props: `turnId`. Two icon buttons (`aria-label` "Good answer" /
  "Bad answer", `aria-pressed`). A click calls `sendFeedback(turnId, rating)` at once. Once a rating is saved it shows
  a one-line input ("Add a comment (optional)", max 1000) and a "Send comment" button, which posts the same rating with
  the comment and then shows "Comment saved". A failure shows "Couldn't save your feedback. Try again." and leaves the
  buttons usable. State is local; a new session clears it with the turns.
- **`api.ts`:** `sendFeedback(turnId, rating, comment?)` with the guest headers; `turn_id` on the final `ChatEvent`
  data; `description` on `DocumentSummary`; `document_id` on `Citation`.
- **`Chat.tsx`:** `Turn` gains `turnId`; `FeedbackControl` renders under answer, refused and clarify replies when
  `turnId` is set. `CitationCard` takes `onOpen?: () => void` and renders a button "Open page →" when the citation has
  `document_id`, `version` and `page`; the click sets the existing `viewer` state. The `<a target="_blank">` is removed
  (the viewer already has an "open in new tab" link).
- **`lib/starters.ts` (new):** `STARTERS: Record<string, string[]>` keyed by `document_key`, and
  `startersFor(documents, scopeId)`: the selected document's list, or the first question of each ready document when
  none is selected. Replaces `SUGGESTED_QUESTIONS`. A document without an entry contributes nothing.
- **`DocumentCards.tsx` and `Documents.tsx`:** show `description` under the title when present.

**Starters (draft, edit freely).** The first of each list is the one shown when no document is selected. Existing
golden cases are reused verbatim; "new" ones are added to `golden.json`.

| Document | Question | Golden case |
|---|---|---|
| Tremblay | What is the fee schedule in the Tremblay agreement? | `fee-schedule` |
| Tremblay | How many days of notice are needed to terminate the Tremblay agreement? | `termination` |
| Tremblay | Which law governs the Tremblay agreement? | `governing-law` |
| Calamos | What is the Calamos Emerging Market Equity Fund's rate in excess of $26 billion? | `calamos-top-tier` |
| Calamos | What rate applies to the first $500 million of the Calamos Emerging Market Equity Fund's assets? | new |
| Calamos | What are the Calamos Emerging Market Equity Fund's fees calculated on? | new |
| AIM | What annual rate applies to the first $500 million for AIM Global Trends Fund? | `aim-first-tier` |
| AIM | How many days of notice are needed to terminate the AIM Global Trends Fund agreement? | new |
| AIM | What is the full fee schedule for AIM Global Trends Fund? | new |
| Voyageur | What is the fee schedule for the Nomura Tax-Free Colorado Fund? | new |
| Voyageur | What rate applies to the Nomura Tax-Free Colorado Fund's assets in excess of $2.5 billion? | new |
| Voyageur | How often is the management fee paid for the Nomura Tax-Free Colorado Fund? | new |

Seven new golden cases bring the set to 37. A starter that fails the gate is reworded or replaced before shipping;
a starter is never shipped outside the golden set.

## 7. Testing

- **Backend (pytest):** `record_feedback` and the route: 201 and the stored row; latest-wins with two rows; 400 without
  a guest; 404 for an unknown turn and for another guest's turn; 429 on the sixth row; comment tokenised; blank comment
  stored as NULL; body over 1000 characters answers 422. Grants: as `ledger_demo`, INSERT succeeds and UPDATE and
  DELETE fail. Stream: every final event carries `turn_id` equal to the saved turn. Documents: the list returns the
  description, and `null` without one. Citations carry `document_id`.
- **Frontend (vitest):** `startersFor` (unscoped, scoped, unknown key); `FeedbackControl` (click posts, comment posts
  the same rating, failure message); `CitationCard` calls `onOpen` and renders no link without a page.
- **Guard:** a test asserts every string in `STARTERS` appears in `golden.json` as an answerable retrieval case.
- **End to end (Playwright):** one new test on the deployed site: pick a starter, get a cited answer, open the citation
  in the viewer, give a thumbs-up, add a comment.
- **Eval gate:** two runs against the demo configuration after `golden.json` changes.

## 8. Rollout

1. `backend/script.demo.md` gains a "P5 + P8 (migration 0015)" section: the migrate commands with the expected head
   `0015_feedback_descriptions`, the check queries (both tables exist, `ledger_demo` INSERT `t` and UPDATE `f` on
   `chat_feedback`, four description rows), and the feedback read query (latest row per guest and turn, joined to
   `chat_turns` for question, outcome and prompt version).
2. `backend/script.demo.sh`: `check` runs the new check queries; a new `feedback` subcommand prints the read query's
   result.
3. The user runs `./script.demo.sh migrate` before the code deploys. The migration is additive, so the running API is
   unaffected until the new code arrives.
4. Deployed verification: curl the feedback route (201, 404, 429), `./script.demo.sh check` and `feedback`, and both
   Playwright files. Report what was and was not checked.
5. The changelog's "Demo-mode decisions" already records the guest-visible behaviour (commit `a37edd1`).

## 9. Out of scope

A feedback read endpoint or dashboard count; the end-of-chat prompt; the P7 usage log (it joins `chat_feedback` by
turn); a guided tour (X1); the two-pane viewer (X2); restoring feedback state after a reload.

## 10. Lenses applied

- **Postgres practice:** least privilege per role (INSERT only), an index for the one known join, CHECK constraints at
  the boundary (D1, D9, §4).
- **Data-systems thinking:** an append-only fact table with latest-wins derived at read time; no copied prompt version
  (D1–D3).
- **Clean architecture:** thin route, logic in `assistant/feedback.py`, DB access only in each package's `dao.py` (§5).
- **Frontend design:** the control says what it does and reports what happened; one extra element per reply (§6).
