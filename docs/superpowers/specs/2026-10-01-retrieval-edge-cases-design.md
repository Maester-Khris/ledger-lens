# Retrieval Edge Cases (P4) — Design

**Date:** 2026-10-01 · **Branch:** `feat/pre-launch-demo` · **Backlog:** P4 (pre-launch sprint) · **Not epic-tracked**
**Status:** approved in brainstorming 2026-10-01, pending written-spec review.
**Research:** `artifacts/research/2026-10-01-rag-edge-cases.md` (local, gitignored). Section numbers (§) below refer to this spec.

## 1. Purpose

Guests will type things the corpus can't answer: blank input, gibberish, off-topic chat, questions about terms the four
contracts don't contain, and questions too vague to search. Today some of these get a weak or improvised answer:

- The relevance gate (`retrieval/search.py`) only fires when full-text search finds **nothing**. A query whose words all
  appear in one passage (e.g. "fees", "fee fee fee") opens it, and then even low-similarity passages are fused into the
  model's context.
- The output check (`assistant/citations.py`) blocks uncited answers and unsupported **numbers**, but not a claim the
  cited passage doesn't actually make ("relevant but insufficient"), which the research identifies as the main RAG
  failure.
- A refusal's wording comes from the model, so it varies, and only the not-comparable case (N11) carries a visible
  system reason.
- Vague questions have no path except a guess or a refusal.
- The golden set has one unanswerable case, so none of this is measured.

P4 makes every one of these an explicit, measured behaviour, without adding a model call per turn.

## 2. Success criteria

1. A question whose only link to the corpus is that all its words appear in one passage (unit-tested in
   `tests/test_retrieval_search.py`) gets the explicit no-evidence refusal, not an answer.
2. Every refusal shows fixed text and a `system` citation card; the model's own refusal wording is never shown.
3. A question too vague to search gets exactly one clarifying question naming the indexed contracts; it is stored as
   outcome `clarified` and never contains figures.
4. "What is the management fee?" with no contract named (chat not scoped) gets a per-contract, cited answer.
5. A whitespace-only message is refused by the API with 422.
6. The golden eval gate passes: zero over-refusal of answerables; junk acceptable rate at least 90% overall and at least
   75% in every junk category (3 of 4; `out_of_corpus` has 5 with the existing `not-in-corpus` case), measured against
   the live demo configuration.
7. With all of the above, every existing test passes; the normal suite makes no LLM call.

## 3. Decisions (settled 2026-10-01)

| # | Decision | Rejected alternatives and why |
|---|----------|-------------------------------|
| D1 | One absolute cosine threshold (`MIN_DENSE_SIMILARITY`), recalibrated on answerable + junk cases | Relative cutoff (Weaviate autocut: needs long result lists); reranker score (new paid dependency, needs calibration anyway) |
| D2 | The dense score must always pass; full-text search only ranks. Below-threshold dense hits are dropped before fusion | Keep today's "full-text hit opens the gate" (keyword junk gets through); threshold full-text rank (no meaningful absolute scale) |
| D3 | No LLM sufficiency check now; documented trigger to add one (§8) | Add it now (extra call per turn: latency against the 60 s turn timeout, spend on a public demo, ~7% judge disagreement; the gain was measured on open-domain multi-hop data, not four contracts) |
| D4 | Prompt rule: state only what a cited passage or tool result explicitly says, otherwise refuse | Rely on the output check alone (it checks numbers, not claims) |
| D5 | No contract named, chat not scoped: answer per contract when the corpus has it; one clarifying question only when too vague to search (option A) | Always ask which contract (extra round trip on answerable questions); refuse (over-refusal) |
| D6 | Refusals are explicit and system-credited: fixed text + a `system` citation | Show the model's wording (varies; can't be counted consistently) |
| D7 | Go/no-go gate (option A): over-refusal = 0; junk acceptable ≥ 90% overall and ≥ 75% per category | Looser 80% with no per-category floor (a whole category can fail unseen); record only (an unenforced threshold is not a control, NIST GV-1.3-002) |
| D8 | Tighten what exists in place (approach 1) | Pre-retrieval classifier (another call or ruleset per turn; the research treats scope rails as soft); reranker (D1) |
| D9 | *(amended 2026-10-01, first gate run)* A clarifying question's text is deterministic: the model only sets `clarification`; the service writes the text from the indexed contract titles | Model-written question (it left the text empty in 5 of 6 clarifications in the first gate run; a figure check on free text is then needed) |
| D10 | *(amended)* Strict answers: never assert that something does not exist, is not charged or does not apply; a question about something no source mentions is refused, not answered with related facts | Allow "the contract does not charge X" (a source not mentioning a thing is not evidence about it; this is how out-of-corpus questions were answered through the fields tool) |
| D11 | *(amended)* `nonsense` accepts a clarification or a refusal; `nonsense-keywords` is replaced by real nonsense ("Fee the banana tier of seven moons") | Refusal only (asking what the guest means is a reasonable reply to gibberish); keep "fee fee fee" (a fee summary is a defensible reading of it, so it is not nonsense) |
| D12 | *(amended)* The agent looks contracts up instead of asking which one (topic named, no contract: `list_documents`, then each contract, at most four) and stops calling tools after two empty searches in a row | Clarify when no contract is named (over-refusal of "What is the management fee?"); unbounded searching (step-limit refusals) |
| D13 | *(amended)* Step-limit and timeout refusals carry the same `system` citation as every other refusal; their texts are unchanged | No citation on those two paths (inconsistent with D6) |
| D14 | *(amended 2026-10-01, second gate run)* Absence claims ("does not charge X", "there is no X", "no X applies") are rejected by the deterministic output check unless a cited source says the same words; a pattern list in `citations.py` | Prompt rule alone (D10 failed twice in the second gate run); the §8 LLM check now (it remains the upgrade path when a rephrasing slips past the patterns) |

## 4. Retrieval gate (§ applies to the `search_contracts` tool only)

`app/retrieval/search.py`, in `search(...)`:

1. After the dense matches are resolved to current elements, keep only those with `score >= config.MIN_DENSE_SIMILARITY`.
2. If none remain, return `[]` (no evidence), **whatever full-text search found**.
3. Fuse full-text hits with the **kept** dense hits only (`reciprocal_rank_fusion` unchanged).

Questions answered through the validated contract fields (`get_contract_fields`, `compare_contract_to_billing`) do not go
through this gate, so it cannot block them.

**Contingency (not built unless calibration demands it):** if a golden answerable exact-term question has its best dense
score below the chosen threshold while full-text finds the right clause, add a second, lower floor that applies only when
full-text also matched. Only with that failing case as its test.

## 5. Calibration

New `backend/scripts/calibrate_relevance.py` (run from `backend/` with the demo env, §9):

- Reads `tests/eval/golden.json` (answerable and junk cases).
- For each case: embeds the question with the production embedding model and queries the production Pinecone index
  (tenant namespace, `config.SEARCH_CANDIDATES`), then resolves current elements the same way `search()` does, and
  records the best dense score. No LLM call; a run costs fractions of a cent.
- Prints a table sorted by score: case id, category, expect, best dense score.
- Suggests `threshold = min(best score of answerable search-dependent cases) - 0.01` and prints the junk-refusal rate the
  retrieval gate alone would reach at that value (cases whose best score falls below it).
- Writes `reports/relevance-<eval_config_hash>.json` with the table, the suggestion and the value currently configured.

The chosen value is set in `backend/.env.demo` / Railway variables and as the code default in `config.py`, with a comment
giving the date and the report. Re-run after any change to the embedding model, corpus, chunking or index.

"Search-dependent" = cases whose expected answer comes from free-text search, not from the validated fields. Each golden
case gains an optional `"retrieval": true` flag to mark it (§7); the calibration only lets those cases set the floor.

## 6. Answer path

### 6.1 Answer format
`app/assistant/graph.py`, `class Answer(BaseModel)`: add `clarification: bool = False`.

### 6.2 Prompt (`app/assistant/prompts/answer_v1.md`)
Add three rules (wording finalised in the plan; changing the file changes `prompt_version()` automatically):
1. State only what a cited passage or tool result explicitly says. If nothing explicitly supports an answer, set
   `refused` to true. *Amended 2026-10-01 (D10):* never say that something does not exist, is not charged or does not
   apply; if the question asks about a term, fee, party or event that no source mentions, refuse instead of answering
   with related facts.
2. If the question names no contract and the chat is not scoped to one, and passages from several contracts answer it,
   answer per contract (at most four), citing each part.
3. If the question is too vague to search or answer, set `clarification` to true and leave `text` empty
   (*amended 2026-10-01, D9*: the clarifying question is written by the service, §6.5).

The agent prompt (`agent_v1.md`) gains two rules (*amended 2026-10-01, D12*): when the question names a topic but no
contract, call `list_documents` and look the topic up in each contract (at most four) instead of asking which one; and
stop calling tools after two searches in a row return nothing.

### 6.2a The answer model also runs when nothing was retrieved (*amended 2026-10-01, plan*)
Today the graph's `answer` node returns the no-evidence refusal without calling the model when there are no sources, so
a vague question could never become a clarifying question. The shortcut is removed: with no sources, `verify_answer`
only lets a refusal or a figure-free clarification through, and the `refuse` node returns `NO_EVIDENCE_MESSAGE` when the
turn retrieved nothing (else `FAILED_VERIFICATION_MESSAGE`). Cost: one model call on turns that retrieved nothing,
bounded by the P3 rate limit.

### 6.3 Output check (`app/assistant/citations.py`, `verify_answer`)
Signature gains `clarification: bool`. *Amended 2026-10-01 (D9):* a clarification always passes, because its text is
written by the service and the model's text is discarded. Everything else is unchanged.

### 6.4 Explicit, system-credited refusals (`app/assistant/service.py`)
- The not-comparable path (N11) is unchanged.
- Every other refusal is shown with fixed text and a `system` citation
  `{"id": SYSTEM_CITATION_ID, "kind": "system", "source": "indexed contracts", "detail": "No passage in the indexed contracts supports an answer to this question."}`:
  - no evidence (the graph's `NO_EVIDENCE_MESSAGE` path) and a model-chosen refusal both use `NO_EVIDENCE_MESSAGE`
    ("I can't find that in the indexed contracts, so I won't guess.");
  - a failed output check keeps `FAILED_VERIFICATION_MESSAGE` (different cause).
- The model's own refusal text is never shown and is not stored as the answer.

### 6.5 Clarifying questions
- `run_turn` yields `TurnEvent("clarify", {"text": ..., "citations": []})` when `answer.clarification` is true.
- *Amended 2026-10-01 (D9):* the text is fixed wording written by the service, never the model's: it names the indexed
  contracts (at most four titles) when the chat is not scoped, only the scoped contract when it is, and neither when
  nothing is indexed. The same text is stored as the turn's answer.
- New `ChatOutcome.clarified`. Migration `0014_chat_outcome_clarified`:
  `ALTER TYPE chat_outcome ADD VALUE IF NOT EXISTS 'clarified'`; downgrade is a documented no-op (Postgres cannot drop
  an enum value), which keeps the upgrade/downgrade/upgrade round-trip test green. No new grant: `ledger_demo` already
  inserts into `chat_turns`.

### 6.6 Empty input
`app/routes/chat.py`, `ChatIn.message`: strip whitespace before the length check (pydantic `StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)`), so `"   "` gets a 422. The UI already disables send for blank input.

## 7. Evaluation

### 7.1 Golden set schema (`tests/eval/golden.json`)
Each case gains:
- `category`: `answerable`, `explained`, `out_of_corpus`, `false_premise`, `underspecified`, `nonsense`, `off_topic`;
- `expect`: `answer`, `refuse` or `clarify` (replaces `expect_refusal`);
- optional `retrieval: true`, which lets the case set the calibration floor (§5). *Amended 2026-10-01 (plan):* field-tool
  answers also cite element ids, so search-only cases can't be told apart in the reports; every answerable case that cites
  `element` passages is marked (conservative: the floor leans to recall).

Existing cases: the six answerables become `answerable` / `answer`; `not-in-corpus` becomes `out_of_corpus` / `refuse`;
`fund-not-comparable` becomes `explained` / `refuse` and keeps `expect_system_notice`, now checked as a `system`
citation with `source == "billing records"` (*amended 2026-10-01, plan*: every refusal carries a system citation after P4).

### 7.2 New cases (for review)
New answerable case (option A):
- `management-fee-unscoped` — "What is the management fee?" → `answerable` / `answer`, `expect_numbers: []`, `expect_page: null` (a cited per-contract answer).

Junk cases. Terms below were checked absent from every contract's text on 2026-10-01 (performance fee, hurdle,
arbitration, minimum account, increase, cryptocurrency, rebate, soft dollar, Maryland):

| id | category | expect | question |
|---|---|---|---|
| ooc-performance-fee | out_of_corpus | refuse | What performance fee does the Tremblay agreement charge? |
| ooc-hurdle-rate | out_of_corpus | refuse | What hurdle rate applies to the AIM Global Trends Fund's advisory fee? |
| ooc-arbitration | out_of_corpus | refuse | Which arbitration body handles disputes under the Calamos agreement? |
| ooc-minimum-account | out_of_corpus | refuse | What is the minimum account size required under the Tremblay agreement? |
| fp-calamos-increase | false_premise | refuse | Why did the Calamos agreement increase its management fee in 2025? |
| fp-crypto-surcharge | false_premise | refuse | How much is the cryptocurrency custody surcharge in the Voyageur agreement? |
| fp-soft-dollar-rebate | false_premise | refuse | What rebate does the Tremblay household receive on soft-dollar commissions? |
| fp-maryland-office | false_premise | refuse | Which Maryland office signed the AIM Global Trends Fund agreement? |
| under-allowed | underspecified | clarify | Is it allowed? |
| under-how-much | underspecified | clarify | How much is it? |
| under-change-it | underspecified | clarify | Can they change it? |
| under-other-one | underspecified | clarify | What does the other one say? |
| nonsense-keys | nonsense | refuse | asdjkl123 |
| nonsense-purple | nonsense | refuse | How do I turn purple into time? |
| nonsense-keywords | nonsense | refuse | Fee the banana tier of seven moons |
| nonsense-marks | nonsense | refuse | ????? |
| off-weather | off_topic | refuse | What's the weather in Montreal today? |
| off-poem | off_topic | refuse | Write me a poem about the ocean. |
| off-world-cup | off_topic | refuse | Who won the 2022 World Cup? |
| off-capital | off_topic | refuse | What is the capital of Japan? |

*Amended 2026-10-01 (D11):* `nonsense-keywords` was "fee fee fee"; the first gate run answered it with a fee summary
through the fields tool, which is a defensible reading, so it is now real nonsense. The D2 regression (a keyword match
alone does not open the gate) is covered by the unit test, not by a golden case. For `underspecified` and `nonsense`,
a clarifying question or a refusal both count as acceptable (§7.3).

### 7.3 Metrics (`tests/eval/test_golden.py`)
- Answerable (`answerable`, `explained`): today's `refusal_ok`, `citation_hit`, `numbers_ok`, plus **over-refusal** =
  share of `answerable` cases that were refused or clarified.
- Junk: **acceptable** per case = refused for every category; refused or clarified for `underspecified` and
  `nonsense` (*amended 2026-10-01, D11*). Reported per category and overall.
- The report also records `MIN_DENSE_SIMILARITY` and the path of the latest relevance report.

### 7.4 Gate (D7)
`test_golden_set` fails unless: over-refusal = 0; junk acceptable ≥ 0.90 overall; every junk category ≥ 0.75
(3 of 4; `out_of_corpus` has 5 cases including the existing `not-in-corpus`).
This replaces `refusal_ok >= 0.5`. The test stays behind the `eval` marker. A run is about 29 chat turns (a few cents).

### 7.5 Config hash
`eval_config_hash()` adds `config.MIN_DENSE_SIMILARITY`, so a report is never attributed to another threshold. (The
dashboard's eval tile shows the report for exactly this hash, so it reads "none" until the eval is re-run after a
threshold change; that is intended.)

## 8. Deferred: LLM sufficiency check
Not built. **Trigger:** the gate (§7.4) fails on `out_of_corpus` or `false_premise` after §6.2 lands. Then: an LLM check
on (question, retrieved context) on the free-text search path only, with the cheaper model, before the single verified
answer event (so streaming is not an issue); "insufficient" goes to the no-evidence refusal (§6.4).

*Note, 2026-10-01:* the first gate run did fail on `out_of_corpus`, but both failing cases were answered from the
validated-fields tool, not from free-text search, so the search-path check described here would not have covered them.
D10 (strict answer prompt) targets that path first; this check stays deferred unless the gate still fails after D10.

## 9. Where calibration and eval run
Against what guests use: `ENV_FILE=.env.demo` plus `backend/.env.demo.local` (local copy of the demo database,
`contract-demo` Pinecone index, demo PII keys, tracing off). Same as the demo ingest.

## 10. Frontend
- `api.ts`: `ChatEvent` gains `clarify`.
- `screens/Chat.tsx`: turn outcome gains `clarified`, rendered as a neutral "Clarifying question" card (no citations),
  focus back on the input.
- Refusals: the existing "No answer" header and the existing `system` citation card show the new reason; no extra UI.

## 11. Testing
Normal suite (deterministic, no LLM):
- gate: keyword match + only weak dense hits → `[]`; mixed scores → below-threshold dense hits absent from the fused
  result; a strong dense hit → evidence returned;
- `verify_answer`: clarification without numbers passes; with a number fails; uncited answer still fails;
- `run_turn` with the scripted fake model: a model-chosen refusal is replaced by `NO_EVIDENCE_MESSAGE` + the system
  citation; a clarification streams `clarify` and stores `clarified`;
- API: whitespace-only message → 422;
- migration round-trip stays green.
End-to-end (`frontend/e2e`, against the deployed demo): a nonsense question shows the "No answer" card with its system
reason. Eval (`-m eval`, demo env): the gate in §7.4, after calibration (§5).

## 12. Out of scope
Reranker and pre-retrieval classifier (D8); LLM sufficiency check (§8); starter questions and the document list (P8);
feedback (P5); production refusal-rate logging (P7).

## 13. Lenses that informed the design
- **Industry research (2026-10-01):** explicit abstention signal + fixed message (Google, AWS, Anthropic); thresholds
  calibrated on own data as a precision/recall dial (Cohere, Microsoft, AWS); paired metrics and over-abstention as a
  failure (UAEval4RAG, TACL survey); go/no-go thresholds and monitoring (NIST AI 600-1).
- **Pragmatic Programmer (contracts, crash early):** clarifications cannot carry figures; refusals are deterministic.
- **Clean Code / DRY:** one gate in `search()`, one output check, one refusal mapping in the service.
- **DDIA (derived data):** the calibration report is the documented operating point of a derived signal (cosine scores),
  re-derived when its inputs change.
- **Clean Architecture:** no new component; each change sits where its concern already lives.
