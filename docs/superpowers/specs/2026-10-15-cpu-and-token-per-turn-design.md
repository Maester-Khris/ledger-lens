# CPU per turn (C1-C3) and tokens per turn (T1-T7): design

Date: 2026-10-15 · Sprint: `feat/measured-evidence` · Status: approved in brainstorming, awaiting spec review
Follows: `docs/superpowers/specs/2026-10-15-chat-throughput-and-shared-limiter-design.md` (N4, N5). Code freeze
Sun 2026-10-18 12:00. Inputs: `backend/reports/load/2026-10-15-profile-gil-40.md` (CPU),
`artifacts/research/2026-10-15-agent-context-token-management.md` (tokens).

## 1. Goal and how it is judged

Lower the CPU and the input tokens one chat turn costs, without losing answer quality, with every number backed by a
run that states its method, box, sample size and limit.

- **CPU headline:** peak turns/s on the 1 vCPU / 1 GB box (80-conversation step) and CPU per turn at 40
  conversations (API CPU % (max) x 10 / turns/s, in ms). Counter-metric: failed turns.
- **Token headline:** median and p95 input tokens per turn, and median $ per answer from the gate's `chat_turns`.
  Counter-metric: the golden gate (answerable behaviour, citation and numbers; over-refusal; junk), threshold 0.43
  (comparable with the N0.1 and N4 runs).
- **Rule:** one change per measurement row: a load-ladder row per CPU change, a token-script row per token change.
  **Approved deviation:** quality is gated per batch, not per change (OpenAI balance $4.44 on 2026-10-15, about
  $1.25 per gate run): gate 1 after batch A (T1, T3, T2), gate 2 after batch B (T4-T7).
- History trimming and session caches are out of scope (last resort; research Concern 4).

## 2. Starting point

| Measure | Value | Source |
|---|---|---|
| Peak turns/s, 1 vCPU | 10.07 at 80 conversations, p95 12.67 s, 0 failed | `2026-10-15-n4-short-sessions.steps.md` |
| CPU per turn at 40 | 87% at 7.75 turns/s, about 112 ms | same |
| Python CPU per turn (py-spy) | about 90 ms: `list_documents` 15.5%, PII tokenising 15%, graph build 9.5% | `2026-10-15-profile-gil-40.md` |
| Input tokens per turn | median 18,391 (150 real turns), $0.037 per answer at list price | changelog N1 |
| Shape | a search result of about 6.1k tokens sent twice (agent call 2 and answer call), about 90% section context; the 102-title list (about 8.2k) re-sent on later calls of calculation and topic-without-contract turns | research note, context |

The token script (section 5) is run once on the current code first (label `t0`) to give the token rows their
"before".

## 3. Section 1: CPU

Order C1, C2, C3a, C3b. Each one is a ladder run, `BOX=1:1G:1 backend/scripts/load/run_chat.sh <label>`, with a
`.steps.md` table. None changes what the model sees, so no gate runs for them alone. Gate 1 covers them.

### C1: one query for the document list

- `documents_dao.document_titles(session, tenant_id, document_id=None) -> list[DocumentTitle]` (frozen dataclass:
  `id`, `document_key`, `title`): one `SELECT` on `documents`, ordered like `list_documents` (`created_at desc`),
  filtered in SQL when `document_id` is set.
- Callers: the `list_documents` tool (`tools._list_documents`) and `service._clarifying_question`. The documents API
  keeps `list_documents` / `_row` (it needs versions, events, counts, descriptions).
- The tool output stays byte-identical in C1 (key kept), so the row measures CPU only; T3 drops the key.
- Tests: the tool's JSON on seeded documents equals the pre-change JSON (scoped and unscoped); one statement per call
  (SQLAlchemy `before_cursor_execute` counter).

### C2: compile the graph once

- `build_graph(chat_model, tools)` no longer takes `ctx` or `open_session`. Nodes read both from
  `config["configurable"]` (`ctx`, `open_session`; `open_session` absent = `nullcontext(ctx.session)` as today).
- `AssistantRuntime` gets a `graph` cached property (compiled once per runtime, which is once per process).
  `run_turn` passes `{"configurable": {"ctx": ..., "open_session": session_factory}}` with the existing
  `recursion_limit`, callbacks and metadata.
- The tool-bound model is prepared once per `tool_choice` value (`bind_tools` today runs on every agent call), and
  the structured-output runnable once.
- Tests: existing graph tests build once and pass ctx through config; new: one compiled graph runs two turns with
  different `ctx` (different scoped document) and each sees only its own.

### C3a: one array parameter for the vault lookup

- In `tokenize_known_values`, the lookup of known tokens becomes `PiiToken.token = ANY(:tokens)` with one Postgres
  array parameter, instead of an `IN` list of about 500 bind parameters (the profile's `_split_query`, cache-key and
  coercion time).
- Tests: the existing redaction and privacy tests (`test_documents_redact.py`, `test_privacy_end_to_end.py`) pass
  unchanged.

### C3b: one keyed HMAC per call

- Tokens include the entity type inside the HMAC message, and the vault already stores them, so one HMAC per window
  for all types would change every stored token. Kept byte-identical instead:
  `redact.token_maker(tenant_id, key) -> Callable[[entity_type, normalised value], str]` keys one HMAC object with
  the `"{tenant_id}|"` prefix once and `.copy()`s it per candidate; each window's value is normalised once, not once
  per type. `make_token` is rebuilt on `token_maker`, so the token format lives in one place.
- Tests: a pinned token for a fixed tenant, type, value and key (format guard); `token_maker` equals `make_token`
  over every type and a set of values (case, spacing); privacy tests unchanged.

After C3b: one py-spy GIL profile at 40 conversations (same command as `2026-10-15-profile-gil-40.md`) to show the
new split. Cost $0.

## 4. Section 2: tokens

### Batch A: T1, T3, T2, then gate 1

**T1: each section's context sent once.**
- `_search_contracts` returns `{"sections": {"S1": {"document", "section", "text"}}, "hits": [{"id", "section":
  "S1", "page", "text"}]}`: one section entry per (version id, section path); hits point to it. `search` computes
  `section_texts` once per section (also fewer queries). Hit text, sources, citations and the verifier are unchanged.
- One prompt line tells the model the shape (prompt version changes; recorded with the gate).
- `scripts/load/mock_openai._first_passage` reads `hits[0]`; its unit test follows.
- Tests: two hits in one section give one section entry; hits in two documents' same-named sections give two.

**T3: the document list, smaller and sent less.**
- Drop `document_key` from the tool output (id and title only).
- Scoped chat: `route` does not force `list_documents`; the agent's messages get one line
  "This chat is limited to one contract: <title> (document_id <id>)." The title is read in `_open_turn`.
- Clearing after use: a pure `model_view(messages, call)` in `graph.py` builds what each model call is sent; the
  state keeps everything. A `list_documents` result that a later AI message has already followed is replaced by
  "[document list shown earlier; call list_documents again if you need it]". The tool call and its ToolMessage stay
  paired (OpenAI requires a result for every call).
- Tests: `model_view` unit tests (cleared only after use, pairing kept, other tools untouched); a scoped calculation
  turn makes no `list_documents` call and still passes the forced tool its document id.

**T2: the agent sees hits, the answer call sees passages.**
- `model_view(..., call="agent")` drops `sections` from search results; hits keep id, section ref, page and their
  own short text, so the agent can still judge whether to search again. `call="answer"` sends the full result.
- Tests: `model_view` unit tests for both call kinds.

**Gate 1** (traced, see section 6).

### Batch B: T4, T5, T6, T7, then gate 2

**T4: one prompt prefix for every call.**
- Every call starts with the same system prompt and the same tool definitions in the same order. The answer call
  sends the tools with `tool_choice="none"` (`with_structured_output(Answer, method="json_schema",
  include_raw=True, tools=...)`, supported in langchain-openai 1.6.5) and appends the answer instructions as a final
  system message.
- Expected effect after T2: the answer call's prefix matches agent call 2 up to the first search result (agent
  calls see it compacted), so the cache read covers system prompt, tools, history, question and earlier tool calls,
  not the search result itself. Measured, not assumed: the token script's shared prefix, then Langfuse
  `cached_tokens` per generation in gate 2 against gate 1.
- Tests: the answer call's request starts with the same system message and tools as the agent's (fake model records
  its inputs); the mock still answers a request carrying both tools and `response_format`.

**T5: a lean retry.**
- After failed verification, the retry is sent: system prompt, the question, the failed answer, the violations, and
  the passages it cited that exist in this turn's sources; if none of its citations is valid, every hit text of the
  turn (no section context). Not the whole turn again.
- Tests: the retry call's messages contain the violations and cited passages and no earlier tool results; the
  existing retry and partial-sections tests pass.

**T6: shorter system prompts.**
- Tighten `agent_v1.md` and `answer_v1.md` (new files `*_v2.md`, prompt version changes) keeping every rule: tool use,
  data-not-instructions, token preservation, no computing, refusal and clarification rules (P4), sections per
  contract, history is not a source.
- Tests: existing graph and service tests; the token row and gate 2 judge it.

**T7: top-k 8 vs 5.**
- Retrieval-only check, $0 beyond embeddings: for each answerable golden case, is the expected page among the hits
  at k=5 and at k=8 (`search` as the tool calls it), plus the token-script delta. k becomes 5 only if no answerable
  case loses its expected page; gate 2 runs with the chosen k.

**Gate 2** (traced).

## 5. Token script

`backend/scripts/token_report.py <label>`: runs the 49 expanded golden cases (setup questions included) through
`run_turn` in-process against the local 102-document database, with real retrieval (OpenAI embeddings, a fraction of
a cent; local Pinecone index, never `contract-demo`) and chat answered by `scripts/load/mock_openai` mounted through
`httpx.ASGITransport` (no server, no delay, $0). It records every chat request body and counts it with tiktoken
`o200k_base` (gpt-4.1's encoding): messages, tools and response format.

Output `backend/reports/tokens/<label>.json` and one printed row: median input tokens per call kind (agent 1,
agent 2, answer, retry), median and p95 per turn, and median shared-prefix tokens between consecutive calls of a turn
(an offline estimate of the cacheable part). `tiktoken` is pinned in `backend/requirements-worker.txt` (already
installed through langchain-openai).

Limits, stated with every row: the mock's path (forced tools, one search, stop) stands in for the real model's
choices; tiktoken's count of the serialised request approximates OpenAI's billed count (checked once against gate 1's
`chat_turns`).

## 6. Gates

- `backend/scripts/gate_runs.sh`, threshold 0.43, one run each. The golden test gets the `enable_tracing` mark
  (deferred item in the changelog) so both runs send Langfuse traces; local Langfuse must be up.
- Recorded per gate: pass/fail per group, median and p95 input tokens and $ per answer from `chat_turns`,
  `cached_tokens` per generation and the cache-hit rate from Langfuse (`scripts/cost_report.py`), steps per answer
  (closes N1's open part).
- A gate that fails: report the failing cases, revert the suspect change by name, and run no further gate without
  the owner's go.

## 7. Execution

claude-agy-orch per change: Claude writes and commits the tests in a worktree on `tmp/agy-<name>`, Gemini implements
(`--model gemini-3.8-flash-high`; tests need `OPENAI_API_KEY=test-unused LOADTEST_STUB_VECTORS=1`), Claude reviews
(one resend, then Claude fixes), full suite, rebase, fast-forward into `feat/measured-evidence`, then the
measurement row. Commits: one line, conventional, no AI attribution, files staged by name.

| Step | Estimate |
|---|---|
| C1, C2, C3a, C3b, 4 ladders, profile | 3 to 4 h |
| Token script, t0 | about 1 h |
| Batch A + gate 1 | 2 to 3 h |
| Batch B + gate 2 | 2 to 3 h |

If time runs short: batch B stops after T4, and the rest stays as the prepared answer.

## 8. Lenses used

- clean-architecture: `model_view` is pure and framework-free (what each call sees), the state stays complete;
  the graph's per-turn inputs come through config, the composition root (`AssistantRuntime`) compiles once.
- pragmatic-programmer: DRY on the token format (`make_token` built on `token_maker`); one change per measurement,
  with the batch-gate deviation stated; reversible changes (each one a commit to revert).
- clean-code: a DAO function named for what the tool needs (`document_titles`) instead of widening `list_documents`.
- Research note (Anthropic, Manus, OpenAI): smallest high-signal context per call, references in place of re-sent
  data, clearing re-fetchable results after use, stable prefix first, measure the cache hit rate.
