# Sentry error reporting and chat usage log (P6 + P7)

Pre-launch demo sprint, branch `feat/pre-launch-demo`. Backlog items P6 and P7 in `artifacts/product-backlog.md`. Not epic-tracked (pre-launch triage). Written from the brainstorming session of 2026-10-03.

## Goal

Two things must be true before the demo is shared:

1. Errors on the API and in the browser reach Sentry, with no chat text, guest ids or document content in the event.
2. The launch metric can be read from the database: the share of guest sessions that reach a cited answer, and the time to first byte (TTFB) of each chat reply, with averages and rolling windows computed later in SQL.

Success: a forced error appears in the right Sentry project, and one chat turn has a `client_ttfb_ms` value that the launch-metric query returns.

## Out of scope

- Stored rolling averages or percentiles (computed in queries).
- Source maps, Sentry session replay, Sentry performance traces.
- Any change to Langfuse or the LLM tracing.
- Changes to the `chat_outcome` enum.

## Current state (verified in the repo)

- `chat_turns` already holds one row per chat query: `guest_id`, `session_id`, `outcome`, `citations`, server `latency_ms`, `trace_id`.
- `chat_feedback` references `chat_turns` by `turn_id`.
- `POST /chat` streams SSE. The final `event` names the saved turn so the client can attach feedback (`backend/app/assistant/service.py`).
- `POST /chat/turns/{turn_id}/feedback` requires `X-Guest-Id` and returns 400 without it (`backend/app/routes/chat.py`). The timing endpoint follows the same guard.
- `backend/app/config.py` reads `SENTRY_DSN` and `SENTRY_ENVIRONMENT`. `backend/app/main.py` initialises Sentry only when the DSN is set, with `send_default_pii=False`. These edits are uncommitted in the working tree and are kept.
- `backend/app/routes/health.py` contains a temporary `capture_message` call. It must be removed before the commit.
- The Sentry projects, alerts, and the DSN variables on Railway (API) and Vercel (frontend) already exist. The DSNs are not secrets in the strict sense, but they stay out of git: `backend/.env.local` and `frontend/.env.local` are git-ignored.

## Design

### 1. Sentry on the API (P6)

- Keep the existing init in `app/main.py`, gated on `SENTRY_DSN`. Tests and local runs without a DSN send nothing.
- Add a `before_send` hook. It drops `event["request"]["data"]`, the request body, and any `message` or exception value that contains user text. The hook is a pure function so it can be tested without a Sentry client.
- Keep `send_default_pii=False`. The dashboard data scrubber stays on as a second layer, as the Sentry setup notes describe.
- Pin `sentry-sdk[fastapi]==2.60.0` in `backend/requirements.txt` (already added).

### 2. Sentry in the browser (P6)

- Add `@sentry/react` to `frontend/package.json`. This is one new npm package and is noted in the PR.
- Initialise it in `frontend/src/main.tsx` only when `VITE_SENTRY_DSN` is set. `tracesSampleRate` is 0. `sendDefaultPii` is false.
- Wrap the app in Sentry's error boundary so an uncaught render error is reported and shows a fallback.
- Add a `beforeSend` hook that removes request bodies and breadcrumbs whose category is `fetch` or `xhr` and whose URL contains `/chat`.

### 3. Usage log: migration 0016 (P7)

- `ALTER TABLE chat_turns ADD COLUMN client_ttfb_ms integer NULL`, with a check that the value is between 0 and 60 000 when it is not null.
- The existing grants stay. `ledger_demo` needs `UPDATE` on the single column only, if the demo role is the writer; this is checked in the plan, not assumed here.
- No new table. `chat_turns` is already one row per query.

### 4. Timing endpoint (P7)

- `POST /chat/turns/{turn_id}/timing`, body `{"ttfb_ms": int}`, validated by Pydantic with `ge=0` and `le=60000`.
- Requires `X-Guest-Id`. The turn must belong to the calling guest and tenant; otherwise 404, so one guest cannot read or write another guest's turn.
- Writes only when `client_ttfb_ms` is null. A second call returns 200 and leaves the first value. The first write wins.
- Route stays thin: parse, call a function in `app/assistant/`, return. The write goes through `assistant/dao.py`.

### 5. Client TTFB measurement (P7)

- `streamChat` in `frontend/src/api.ts` records `t0` just before `fetch`, and `t1` at the first call that returns a chunk from the response body reader. The status event counts, as chosen.
- After the stream ends and the final event has named the turn id, the client posts `Math.round(t1 - t0)` to the timing endpoint. The post is fire-and-forget: a failed post never shows an error to the guest.
- If the stream is aborted, no timing is posted, and the column stays null.

### 6. Launch metric

- Cited-answer share per session: sessions with at least one `chat_turns` row where `outcome = 'answered'` and `citations` is a non-empty array, divided by all sessions with at least one turn.
- TTFB: average, and a rolling window over the last N turns, computed in the same query. Nulls are excluded from the TTFB figures and reported as a count.
- Delivered as a SQL view `chat_usage_daily`, plus an entry in `backend/script.demo.sh` (`usage` subcommand), following the existing feedback pattern.

## Testing

- **Backend, pytest:** the timing endpoint rejects values outside 0 to 60 000, rejects a missing `X-Guest-Id`, returns 404 for another guest's turn, writes the first value, and ignores a second. The `before_send` hook removes request data and chat text.
- **Migration:** `alembic upgrade head` and `downgrade -1` on `ledger_test`.
- **Frontend, vitest:** `streamChat` posts a TTFB after the first chunk, and posts nothing when the stream is aborted.
- **Smoke, deployed:** a forced error reaches both Sentry projects in the `demo` environment with no chat text in the event. One real chat turn has `client_ttfb_ms` set, and the usage view returns a row.

## Risks

- TTFB includes the guest's network time. The figures are a range that depends on the connection, not a single server number.
- A turn whose stream never finishes leaves the timing null. The metric skips nulls and reports how many there are.
- The `ledger_demo` role's grants on `chat_turns` must allow the single-column update. This is checked against the demo database before the migration runs.

## Decisions taken

| Decision | Choice | Reason |
|---|---|---|
| Latency measured | Client TTFB, not total | Asked for; first byte of the response body |
| TTFB stop point | First chunk of the response body, including the status event | Literal TTFB definition |
| Storage of aggregates | Computed in SQL, not stored | Average and rolling windows are changed later without a migration |
| Outcome enum | Unchanged; cited answer derived from `citations` | No enum migration; the data is already stored |
| Usage table | None; column on `chat_turns` | One row per query already exists |
| Sentry traces | Off | Demo scope; avoids extra event volume |

## Open items for the plan

- Confirm the `ledger_demo` grant on `chat_turns` (see Risks).
- Where the final SSE event is parsed on the client (`streamChat` is at `frontend/src/api.ts:135`; confirm the event parser sits in the same function).
