# Retrieval Edge Cases (P4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This project:** the executor does Tasks 1–5 in order and stops at each **REVIEW CHECKPOINT** with: the commit hash, the exact test/build/lint output, and `git status`. Task 6 (calibration, eval gate, deploy) is run by Claude with the user, not by the executor.

**Goal:** Junk, vague and unanswerable questions get an explicit, measured behaviour (system-credited refusal or one clarifying question) instead of a weak answer, with no extra model call per turn.

**Architecture:** Tighten what exists in place: the relevance gate in `retrieval/search.py`, the answer prompt and output check in `assistant/`, the refusal mapping in `assistant/service.py`, a `clarify` event and `clarified` outcome, and an enforced golden-set gate with a retrieval-only calibration script.

**Tech Stack:** Python 3.12 / FastAPI / LangGraph / SQLAlchemy 2.0 / Alembic / PostgreSQL 18 / pytest; React (Vite) + TypeScript; Playwright.

**Spec:** `docs/superpowers/specs/2026-10-01-retrieval-edge-cases-design.md` — read it in full first. § numbers refer to it.

## Deviations from the spec (found while mapping the code; the spec is amended to match)

1. **The answer model also runs when nothing was retrieved.** Today `graph.py`'s `answer` node returns the no-evidence refusal without calling the model when there are no sources. A vague question ("Is it allowed?") usually retrieves nothing, so it could never become a clarifying question (spec criterion 3). Task 2 removes that short-circuit; with no sources, `verify_answer` only lets a refusal or a figure-free clarification through, and the `refuse` node returns `NO_EVIDENCE_MESSAGE` when there were no sources. Cost: one extra model call on turns that retrieved nothing (junk), which the P3 rate limit already bounds.
2. **`retrieval: true` marks every answerable case that cites `element` passages.** The latest eval report shows field-tool answers also cite element ids, so search-only cases can't be told apart. Marking all element-citing answerables is conservative (more cases constrain the floor, so the threshold leans to recall).
3. **The explained-refusal check (N11) now requires `source == "billing records"`**, because after P4 every refusal carries a `system` citation.

## Global Constraints

- Branch `feat/pre-launch-demo`. Never commit to `main`/`preview`. Stage files explicitly (never `git add -A`/`.`). Conventional commits; use the commit message each task gives, verbatim. **No AI co-author line, no "Generated with" line.** Do not push.
- Backend commands from `backend/` as `/home/niki/Documents/workenv/pydev/bin/<tool>`; never create a `.venv`. Frontend commands from `frontend/`.
- No new Python dependency, no new npm package.
- Python: type hints on every signature; TypeScript: no `any`, a props interface per component.
- The normal backend suite (`/home/niki/Documents/workenv/pydev/bin/pytest -q`) must pass after every task and must never call a real LLM. The `eval`-marked golden test is **not** run by the executor (it costs money and needs the demo env); Task 6 runs it.
- Only edit existing tests where a task says so.
- The frontend has one known pre-existing failing test ("reverses with a key derived from the posting id so a retry replays"); not yours.
- Do not touch `backend/.env*`, `frontend/.env.vercel`, `backend/script.demo.*`.
- If a step can't be applied as written, STOP and quote the mismatching line; do not adapt.

## Review Focus

1. **A real answerable question must still be answered after the gate change** (the dense floor now always applies). Unit tests use meaningless fake embeddings, so the floor is switched off by an autouse fixture except in the gate tests and the eval. The real check is Task 6's eval: over-refusal must be 0. Test: Task 6 (gate).
2. **A clarifying question must never smuggle a figure** past the output check. Test: Task 2, `test_a_clarifying_question_passes_without_citations_but_not_with_figures`; Task 3, `test_a_clarification_with_figures_is_refused`.
3. **The model's own refusal wording must never reach the user or the stored answer.** Test: Task 3, `test_a_model_refusal_is_shown_as_the_fixed_text_with_a_system_reason`.
4. **A keyword-only junk question** ("fee fee banana tier tier") must not get evidence. Test: Task 1, `test_a_keyword_match_alone_does_not_open_the_gate`; Task 4 golden case `nonsense-keywords`.
5. **A whitespace-only message** must be refused by the API, not reach the agent. Test: Task 3, `test_a_blank_message_is_rejected`.

---

### Task 1: The retrieval gate

**Files:**
- Modify: `backend/app/retrieval/search.py`, `backend/tests/conftest.py`, `backend/tests/test_retrieval_search.py`

**Interfaces:**
- Produces: `search.dense_matches(session, *, tenant_id, query, embeddings, vector_index, document_ids=None) -> list[tuple[uuid.UUID, float]]` (current element id, cosine score, best first; stale vectors removed). Used by `search()` and by the Task 4 calibration script.

- [ ] **Step 1: Switch the floor off for unit tests** — in `backend/tests/conftest.py`, append:

```python


@pytest.fixture(autouse=True)
def dense_floor_off(monkeypatch, request):
    """Unit tests use 8-dimension fake embeddings whose cosine scores mean nothing, so the dense floor is off, except in
    the gate tests (which set it) and in the eval (real embeddings, real threshold)."""
    if "eval" in request.keywords:
        return
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", -1.0)
```

- [ ] **Step 2: Write the failing gate tests** — in `backend/tests/test_retrieval_search.py`, append:

```python


def _scores(index, tenant_id, embeddings, query):
    return sorted((m.score for m in index.query(str(tenant_id), embeddings.embed_query(query), 10, None)), reverse=True)


def test_a_keyword_match_alone_does_not_open_the_gate(db_session, tenant_id, monkeypatch):
    _, embeddings, index = _indexed(db_session, tenant_id, ("Fees are billed quarterly in arrears.",))
    query = "fee fee banana quarterly"  # shares "quarterly" with the clause: a full-text hit
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", _scores(index, tenant_id, embeddings, query)[0] + 0.01)
    assert search(db_session, tenant_id=tenant_id, query=query, embeddings=embeddings, vector_index=index) == []


def test_passages_below_the_floor_never_reach_the_context(db_session, tenant_id, monkeypatch):
    _, embeddings, index = _indexed(db_session, tenant_id, ("Fees are billed quarterly in arrears.", "Governed by Ontario law."))
    query = "zzqx unmatched words"  # no full-text hit: only dense scores decide
    top, second = _scores(index, tenant_id, embeddings, query)[:2]
    assert top > second
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", (top + second) / 2)
    found = search(db_session, tenant_id=tenant_id, query=query, embeddings=embeddings, vector_index=index)
    assert len(found) == 1  # the weaker passage was dropped before fusion
```

  Check `from app import config` is already imported at the top of the file (it is); add it if not.

- [ ] **Step 3: Run them and confirm they fail** — `/home/niki/Documents/workenv/pydev/bin/pytest tests/test_retrieval_search.py -q`. Expected: the two new tests fail (the first returns evidence because full-text opens the gate; the second returns 2 passages).

- [ ] **Step 4: Implement** — in `backend/app/retrieval/search.py`, add above `def search(`:

```python
def dense_matches(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    query: str,
    embeddings: Embeddings,
    vector_index: VectorIndex,
    document_ids: Sequence[uuid.UUID] | None = None,
) -> list[tuple[uuid.UUID, float]]:
    """Dense candidates as (current element id, cosine score), best first. Stale vectors drop out here."""
    matches = vector_index.query(str(tenant_id), embeddings.embed_query(query), config.SEARCH_CANDIDATES,
                                 None if document_ids is None else [str(d) for d in document_ids])
    current = dao.current_element_ids(session, tenant_id=tenant_id, vector_ids=[m.id for m in matches])
    return [(current[m.id], m.score) for m in matches if m.id in current]
```

  and in `search(...)` replace these lines:

```python
    matches = vector_index.query(str(tenant_id), embeddings.embed_query(query), config.SEARCH_CANDIDATES,
                                 None if document_ids is None else [str(d) for d in document_ids])
    current = dao.current_element_ids(session, tenant_id=tenant_id, vector_ids=[m.id for m in matches])
    dense = [(current[m.id], m.score) for m in matches if m.id in current]  # stale vectors drop out here
    if not text_ids and (not dense or max(score for _, score in dense) < config.MIN_DENSE_SIMILARITY):
        return []  # relevance gate: say "I don't know" instead of answering from noise
```

  with:

```python
    # Relevance gate (P4): the dense score decides and full-text only ranks, so a shared keyword alone ("fee") never
    # opens the gate, and passages below the floor never reach the model's context.
    dense = [(element_id, score) for element_id, score in dense_matches(
        session, tenant_id=tenant_id, query=query, embeddings=embeddings, vector_index=vector_index,
        document_ids=document_ids) if score >= config.MIN_DENSE_SIMILARITY]
    if not dense:
        return []  # say "I don't know" instead of answering from noise
```

- [ ] **Step 5: Run the tests** — `.../pytest tests/test_retrieval_search.py -q` → all pass; full suite `.../pytest -q` → no failures.

- [ ] **Step 6: Commit** — `git add backend/app/retrieval/search.py backend/tests/conftest.py backend/tests/test_retrieval_search.py`, then
`git commit -m "feat(retrieval): the dense score alone opens the relevance gate and weak passages are dropped"`.

**REVIEW CHECKPOINT 1.**

---

### Task 2: Answer format, prompt rules and the output check

**Files:**
- Modify: `backend/app/assistant/graph.py`, `backend/app/assistant/citations.py`, `backend/app/assistant/prompts/answer_v1.md`, `backend/tests/test_assistant_citations.py`, `backend/tests/test_assistant_graph.py`, `backend/tests/test_unvalidated_and_notice.py`, `backend/tests/test_api_chat.py`

**Interfaces:**
- Produces: `Answer.clarification: bool = False`; `verify_answer(text, cited_ids, sources, refused, clarification=False) -> list[str]`; the graph's `refuse` node returns `NO_EVIDENCE_MESSAGE` when the turn retrieved nothing, else `FAILED_VERIFICATION_MESSAGE`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_assistant_citations.py`:

```python


def test_a_clarifying_question_passes_without_citations_but_not_with_figures():
    assert verify_answer("Which contract do you mean, Tremblay or Calamos?", [], {}, refused=False, clarification=True) == []
    assert verify_answer("Do you mean the 30-day notice?", [], {}, refused=False, clarification=True) == [
        "a clarifying question must not state figures"]
    assert verify_answer("It is 30 days.", [], {}, refused=False) == ["the answer cites nothing"]
```

- [ ] **Step 2: Run it and confirm it fails** — `.../pytest tests/test_assistant_citations.py -q` → `TypeError: ... unexpected keyword argument 'clarification'`.

- [ ] **Step 3: The output check** — in `backend/app/assistant/citations.py`, change `verify_answer` to:

```python
def verify_answer(text: str, cited_ids: Sequence[str], sources: Mapping[str, str], refused: bool,
                  clarification: bool = False) -> list[str]:
    """Deterministic gate: every number in the answer must appear in something it cites from this turn.
    A clarifying question cites nothing and may not state any figure (P4)."""
    if refused:
        return []
    if clarification:
        return ["a clarifying question must not state figures"] if numbers_in(text) else []
    if not cited_ids:
        return ["the answer cites nothing"]
```

  (the rest of the function body stays as it is).

- [ ] **Step 4: The answer format and the graph** — in `backend/app/assistant/graph.py`:
  - in `class Answer(BaseModel)`, add `clarification: bool = False` after `refused: bool`;
  - in `answer(state)`, **delete** these two lines (the model now runs even when nothing was retrieved, so it can ask a clarifying question):

```python
        if not state.get("sources"):
            return {"answer": Answer(text=NO_EVIDENCE_MESSAGE, citations=[], refused=True), "violations": []}
```

  - in `verify(state)`, pass the flag: `verify_answer(reply.text, reply.citations, state.get("sources", {}), reply.refused, reply.clarification)`;
  - replace the `refuse` node with:

```python
    def refuse(state: TurnState) -> dict:
        text = FAILED_VERIFICATION_MESSAGE if state.get("sources") else NO_EVIDENCE_MESSAGE
        return {"answer": Answer(text=text, citations=[], refused=True)}
```

- [ ] **Step 5: The prompt** — in `backend/app/assistant/prompts/answer_v1.md`, replace the line
  `- If the sources do not answer the question, set \`refused\` to true and say you cannot find it in the indexed contracts.`
  with:

```
- State only what a cited source explicitly says. If no source explicitly supports an answer, set `refused` to true.
- If the question names no contract, the conversation is not limited to one contract, and sources from several
  contracts answer it, answer for each contract separately (at most four), citing each part.
- If the question is too vague to search or answer (for example "Is it allowed?"), set `clarification` to true and ask
  exactly one short clarifying question that names the indexed contracts you know of. Cite nothing and write no numbers.
  Gibberish, off-topic requests and questions about things the contracts don't cover are not vague: refuse them.
```

- [ ] **Step 6: Update the five tests that relied on the no-sources shortcut** (verified by Claude on 2026-10-01: exactly
  these five fail once the shortcut is removed, all with "ScriptedChatModel ran out of replies" or the shortcut assertion):
  - `backend/tests/test_assistant_graph.py`: replace `test_no_evidence_refuses_without_answer_call` with:

```python
def test_with_no_evidence_only_a_refusal_or_a_clarification_gets_through(db_session, tenant_id):
    stated = Answer(text="It is 30 days.", citations=[], refused=False)
    model = ScriptedChatModel(replies=[_search_call("charitable donations"), AIMessage(content="done"), stated, stated])
    state = _run(model, _ctx(db_session, tenant_id, RecordingEmbeddings(), InMemoryVectorIndex()), "Donations?")
    assert state["answer"] == Answer(text=NO_EVIDENCE_MESSAGE, citations=[], refused=True)  # both attempts failed the check
```

  - same file, `test_calculation_question_looks_up_the_id_before_the_forced_tool`: append
    `Answer(text="I can't find that contract.", citations=[], refused=True),` as the last element of `replies=[...]`.
  - `backend/tests/test_unvalidated_and_notice.py`: in `test_unconfirmed_fields_are_announced_before_the_final_event` and
    in `test_not_comparable_refusal_becomes_a_system_notice`, append
    `Answer(text="Not available.", citations=[], refused=True),` as the last element of `replies=[...]`
    (`Answer` is already imported there).
  - `backend/tests/test_api_chat.py`, `test_refusal_is_its_own_event`: append
    `Answer(text="Nothing about donations here, sorry!", citations=[], refused=True),` as the last element of `replies=[...]`
    (Task 3 replaces this test entirely).

- [ ] **Step 7: Run the tests** — `.../pytest tests/test_assistant_citations.py tests/test_assistant_graph.py tests/test_unvalidated_and_notice.py tests/test_api_chat.py -q` → all pass; full suite → no failures. Any other failure: stop and report.

- [ ] **Step 8: Commit** — `git add backend/app/assistant/graph.py backend/app/assistant/citations.py backend/app/assistant/prompts/answer_v1.md backend/tests/test_assistant_citations.py backend/tests/test_assistant_graph.py backend/tests/test_unvalidated_and_notice.py backend/tests/test_api_chat.py`, then
`git commit -m "feat(assistant): answer only what a source states, or ask one figure-free clarifying question"`.

**REVIEW CHECKPOINT 2.**

---

### Task 3: Explicit refusals, the `clarify` event, the `clarified` outcome, blank input

**Files:**
- Create: `backend/alembic/versions/0014_chat_outcome_clarified.py`
- Modify: `backend/app/assistant/models.py`, `backend/app/assistant/service.py`, `backend/app/routes/chat.py`, `backend/tests/test_api_chat.py`

**Interfaces:**
- Consumes: `Answer.clarification`, `NO_EVIDENCE_MESSAGE`, `FAILED_VERIFICATION_MESSAGE` (Task 2).
- Produces: SSE event `clarify` (`{"text", "citations": []}`); `ChatOutcome.clarified`; every non-N11 refusal carries
  `{"id": "system", "kind": "system", "source": "indexed contracts", "detail": "No passage in the indexed contracts supports an answer to this question."}`.

- [ ] **Step 1: Write the failing tests** — in `backend/tests/test_api_chat.py`:
  - add imports: `from app.assistant.graph import Answer, FAILED_VERIFICATION_MESSAGE, NO_EVIDENCE_MESSAGE` (replace the existing `from app.assistant.graph import Answer`);
  - replace `test_refusal_is_its_own_event` with:

```python
def test_refusal_is_its_own_event_with_fixed_text_and_a_system_reason(client, session_factory, tenant_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "donations"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="Nothing about donations here, sorry!", citations=[], refused=True),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-2", "message": "Donations?"}))[-1]
    assert kind == "refused" and data["text"] == NO_EVIDENCE_MESSAGE
    assert data["citations"] == [{"id": "system", "kind": "system", "source": "indexed contracts",
                                  "detail": "No passage in the indexed contracts supports an answer to this question."}]
```

  - append:

```python


def test_a_model_refusal_is_shown_as_the_fixed_text_with_a_system_reason(client, session_factory, db_session, tenant_id):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=("Fees are billed quarterly in arrears.",))
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    model = ScriptedChatModel(replies=[
        AIMessage(content="", tool_calls=[{"name": "search_contracts", "args": {"query": "quarterly"}, "id": "c1"}]),
        AIMessage(content="done"),
        Answer(text="I'd rather not say.", citations=[], refused=True),
    ])
    _override(client, _runtime(model, embeddings, index), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-r", "message": "Is there a fee waiver?"}))[-1]
    assert kind == "refused" and data["text"] == NO_EVIDENCE_MESSAGE and data["citations"][0]["kind"] == "system"
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-r")).one()
    assert turn.answer_redacted == NO_EVIDENCE_MESSAGE  # the model's own wording is never stored as the answer


def test_a_clarifying_question_streams_clarify_and_is_stored_as_clarified(client, session_factory, db_session, tenant_id):
    model = ScriptedChatModel(replies=[
        AIMessage(content="no tool needed"),
        Answer(text="Which contract do you mean: Tremblay or Calamos?", citations=[], refused=False, clarification=True),
    ])
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-c", "message": "Is it allowed?"}))[-1]
    assert (kind, data) == ("clarify", {"text": "Which contract do you mean: Tremblay or Calamos?", "citations": []})
    turn = db_session.scalars(select(ChatTurn).where(ChatTurn.session_id == "s-c")).one()
    assert turn.outcome is ChatOutcome.clarified


def test_a_clarification_with_figures_is_refused(client, session_factory, tenant_id):
    figure = Answer(text="Do you mean the 30-day notice?", citations=[], refused=False, clarification=True)
    model = ScriptedChatModel(replies=[AIMessage(content="no tool needed"), figure, figure])  # both attempts fail the check
    _override(client, _runtime(model, RecordingEmbeddings(), InMemoryVectorIndex()), session_factory)
    kind, data = _events(client.post("/chat", json={"session_id": "s-f", "message": "Is it allowed?"}))[-1]
    assert kind == "refused" and data["text"] == NO_EVIDENCE_MESSAGE  # nothing was retrieved


def test_a_blank_message_is_rejected(client):
    assert client.post("/chat", json={"session_id": "s-b", "message": "   "}).status_code == 422
```

- [ ] **Step 2: Run them and confirm they fail** — `.../pytest tests/test_api_chat.py -q`: the new and replaced tests fail (no system citation, no `clarify` event, `ChatOutcome` has no `clarified`, blank accepted).

- [ ] **Step 3: The outcome and its migration.**
  - `backend/app/assistant/models.py`: in `class ChatOutcome`, add `clarified = "clarified"` after `refused = "refused"`.
  - create `backend/alembic/versions/0014_chat_outcome_clarified.py`:

```python
"""chat outcome 'clarified' (P4): a turn that ended with one clarifying question

Revision ID: 0014_chat_outcome_clarified
Revises: 0013_demo_role_guest_overlays
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014_chat_outcome_clarified"
down_revision: Union[str, Sequence[str], None] = "0013_demo_role_guest_overlays"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE chat_outcome ADD VALUE IF NOT EXISTS 'clarified'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum type. Keeping it is harmless: after a code rollback nothing writes it.
    pass
```

  (Check the revision id of `backend/alembic/versions/0013_demo_role_and_guest_overlays.py` is exactly `0013_demo_role_guest_overlays`; it is 31 characters, under Alembic's 32.)

- [ ] **Step 4: The service** — in `backend/app/assistant/service.py`:
  - change the graph import to `from app.assistant.graph import (FAILED_VERIFICATION_MESSAGE, GRAPH_VERSION, NO_EVIDENCE_MESSAGE, RECURSION_LIMIT, build_graph, prompt_version)`;
  - `TurnEvent.type`: add `"clarify"` to the `Literal[...]`;
  - after `NOT_COMPARABLE_TEXT = ...` add `NO_SUPPORT_DETAIL = "No passage in the indexed contracts supports an answer to this question."`;
  - in `run_turn`, replace the block from the line `cited = [state["citations"][c] | {"id": c} for c in answer.citations if c in state.get("citations", {})]` through the line `yield TurnEvent("refused" if answer.refused else "answer", {"text": text, "citations": shown})` with:

```python
            record["retrieved"] = state.get("retrieved", [])
            record["input_tokens"], record["output_tokens"] = _usage(state.get("messages", []))
            if answer.refused:
                # P4: every refusal but N11 is fixed text plus a system reason; the model's own wording is never shown.
                text = FAILED_VERIFICATION_MESSAGE if answer.text == FAILED_VERIFICATION_MESSAGE else NO_EVIDENCE_MESSAGE
                citation = {"id": SYSTEM_CITATION_ID, "kind": "system", "source": "indexed contracts",
                            "detail": NO_SUPPORT_DETAIL}
                record.update(answer_redacted=text, citations=[citation])
                outcome = ChatOutcome.refused
                yield TurnEvent("refused", {"text": text, "citations": [citation]})
                return
            if answer.clarification:
                record.update(answer_redacted=answer.text, citations=[])
                outcome = ChatOutcome.clarified
                [text] = documents_dao.reveal(session, tenant_id, [answer.text], vault_key)
                yield TurnEvent("clarify", {"text": text, "citations": []})
                return
            cited = [state["citations"][c] | {"id": c} for c in answer.citations if c in state.get("citations", {})]
            record.update(answer_redacted=answer.text, citations=cited)
            outcome = ChatOutcome.answered
            [text, *quotes] = documents_dao.reveal(session, tenant_id, [answer.text, *(c.get("quote", "") for c in cited)], vault_key)
            shown = [c | ({"quote": q} if "quote" in c else {}) for c, q in zip(cited, quotes)]
            yield TurnEvent("answer", {"text": text, "citations": shown})
```

- [ ] **Step 5: Blank input** — in `backend/app/routes/chat.py`: add `StringConstraints` to the `from pydantic import ...` line, and change `message: str = Field(min_length=1, max_length=2000)` to
  `message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]`.

- [ ] **Step 6: Run the tests** — `.../pytest tests/test_api_chat.py tests/test_migrations.py -q` → all pass; full suite → no failures.

- [ ] **Step 7: Commit** — `git add backend/alembic/versions/0014_chat_outcome_clarified.py backend/app/assistant/models.py backend/app/assistant/service.py backend/app/routes/chat.py backend/tests/test_api_chat.py`, then
`git commit -m "feat(assistant): fixed system-credited refusals, a clarify event and outcome, and no blank messages"`.

**REVIEW CHECKPOINT 3.**

---

### Task 4: Golden set, metrics, gate, config hash, calibration script

**Files:**
- Modify: `backend/tests/eval/golden.json`, `backend/tests/eval/test_golden.py`, `backend/tests/test_golden_scoring.py`, `backend/app/assistant/graph.py`
- Create: `backend/scripts/calibrate_relevance.py`

**Interfaces:**
- Consumes: `search.dense_matches` (Task 1); the `clarify` event and system citation sources (Task 3).
- Produces: `test_golden.score_case(case, event_type, data) -> dict` (keys `id`, `category`, `event`, `behaviour_ok`, `citation_hit`, `numbers_ok`), `summarise(results) -> dict`, `gate_failures(summary) -> list[str]`, `JUNK`.

- [ ] **Step 1: The golden set** — replace `backend/tests/eval/golden.json` with exactly:

```json
[
  {"id": "fee-schedule", "category": "answerable", "expect": "answer", "retrieval": true,
   "question": "What is the fee schedule in the Tremblay agreement?",
   "expect_document": "tremblay-ima", "expect_page": 2, "expect_numbers": ["1.00", "0.85", "0.65"]},
  {"id": "termination", "category": "answerable", "expect": "answer", "retrieval": true,
   "question": "How many days of notice are needed to terminate the Tremblay agreement?",
   "expect_document": "tremblay-ima", "expect_page": 1, "expect_numbers": ["30"]},
  {"id": "governing-law", "category": "answerable", "expect": "answer", "retrieval": true,
   "question": "Which law governs the Tremblay agreement?",
   "expect_document": "tremblay-ima", "expect_page": 1, "expect_numbers": []},
  {"id": "calamos-top-tier", "category": "answerable", "expect": "answer", "retrieval": true,
   "question": "What is the Calamos Emerging Market Equity Fund's rate in excess of $26 billion?",
   "expect_document": "calamos-emerging-market-equity", "expect_page": 1, "expect_numbers": ["0.90", "26"]},
  {"id": "aim-first-tier", "category": "answerable", "expect": "answer", "retrieval": true,
   "question": "What annual rate applies to the first $500 million for AIM Global Trends Fund?",
   "expect_document": "aim-global-trends-advisory", "expect_page": null, "expect_numbers": ["0.975", "500"]},
  {"id": "management-fee-unscoped", "category": "answerable", "expect": "answer", "retrieval": true,
   "question": "What is the management fee?",
   "expect_document": null, "expect_page": null, "expect_numbers": []},
  {"id": "leakage", "category": "answerable", "expect": "answer",
   "question": "How much would the Tremblay household pay under its contract compared with what billing charges?",
   "expect_document": "tremblay-ima", "expect_page": null, "expect_numbers": ["400.00"]},
  {"id": "fund-not-comparable", "category": "explained", "expect": "refuse", "expect_system_notice": true,
   "question": "Compare the Calamos fund agreement with billing.",
   "expect_document": "calamos-emerging-market-equity", "expect_page": null, "expect_numbers": []},
  {"id": "not-in-corpus", "category": "out_of_corpus", "expect": "refuse",
   "question": "What was the client's charitable donation amount in 2024?"},
  {"id": "ooc-performance-fee", "category": "out_of_corpus", "expect": "refuse",
   "question": "What performance fee does the Tremblay agreement charge?"},
  {"id": "ooc-hurdle-rate", "category": "out_of_corpus", "expect": "refuse",
   "question": "What hurdle rate applies to the AIM Global Trends Fund's advisory fee?"},
  {"id": "ooc-arbitration", "category": "out_of_corpus", "expect": "refuse",
   "question": "Which arbitration body handles disputes under the Calamos agreement?"},
  {"id": "ooc-minimum-account", "category": "out_of_corpus", "expect": "refuse",
   "question": "What is the minimum account size required under the Tremblay agreement?"},
  {"id": "fp-calamos-increase", "category": "false_premise", "expect": "refuse",
   "question": "Why did the Calamos agreement increase its management fee in 2025?"},
  {"id": "fp-crypto-surcharge", "category": "false_premise", "expect": "refuse",
   "question": "How much is the cryptocurrency custody surcharge in the Voyageur agreement?"},
  {"id": "fp-soft-dollar-rebate", "category": "false_premise", "expect": "refuse",
   "question": "What rebate does the Tremblay household receive on soft-dollar commissions?"},
  {"id": "fp-maryland-office", "category": "false_premise", "expect": "refuse",
   "question": "Which Maryland office signed the AIM Global Trends Fund agreement?"},
  {"id": "under-allowed", "category": "underspecified", "expect": "clarify", "question": "Is it allowed?"},
  {"id": "under-how-much", "category": "underspecified", "expect": "clarify", "question": "How much is it?"},
  {"id": "under-change-it", "category": "underspecified", "expect": "clarify", "question": "Can they change it?"},
  {"id": "under-other-one", "category": "underspecified", "expect": "clarify", "question": "What does the other one say?"},
  {"id": "nonsense-keys", "category": "nonsense", "expect": "refuse", "question": "asdjkl123"},
  {"id": "nonsense-purple", "category": "nonsense", "expect": "refuse", "question": "How do I turn purple into time?"},
  {"id": "nonsense-keywords", "category": "nonsense", "expect": "refuse", "question": "fee fee banana tier tier"},
  {"id": "nonsense-marks", "category": "nonsense", "expect": "refuse", "question": "?????"},
  {"id": "off-weather", "category": "off_topic", "expect": "refuse", "question": "What's the weather in Montreal today?"},
  {"id": "off-poem", "category": "off_topic", "expect": "refuse", "question": "Write me a poem about the ocean."},
  {"id": "off-world-cup", "category": "off_topic", "expect": "refuse", "question": "Who won the 2022 World Cup?"},
  {"id": "off-capital", "category": "off_topic", "expect": "refuse", "question": "What is the capital of Japan?"}
]
```

- [ ] **Step 2: Write the failing scoring tests** — replace `backend/tests/test_golden_scoring.py` with:

```python
from tests.eval.test_golden import gate_failures, score_case, summarise

NOTICE = {"kind": "system", "source": "billing records", "detail": "d"}
NO_SUPPORT = {"kind": "system", "source": "indexed contracts", "detail": "d"}


def _case(category, expect, **extra):
    return {"id": f"{category}-{expect}", "category": category, "expect": expect, "expect_page": None,
            "expect_numbers": [], **extra}


def test_an_explained_refusal_needs_the_billing_records_reason():
    case = _case("explained", "refuse", expect_system_notice=True)
    assert score_case(case, "refused", {"text": "x", "citations": [NOTICE]})["behaviour_ok"]
    assert not score_case(case, "refused", {"text": "x", "citations": [NO_SUPPORT]})["behaviour_ok"]


def test_an_answer_needs_a_matching_citation_and_its_numbers():
    case = _case("answerable", "answer", expect_page=2, expect_numbers=["0.85"])
    result = score_case(case, "answer", {"text": "0.85%", "citations": [{"kind": "element", "page": 2}]})
    assert result["behaviour_ok"] and result["citation_hit"] and result["numbers_ok"]
    assert not score_case(case, "answer", {"text": "0.85%", "citations": []})["citation_hit"]


def test_underspecified_accepts_a_clarification_or_a_refusal_other_junk_only_a_refusal():
    vague, junk = _case("underspecified", "clarify"), _case("nonsense", "refuse")
    assert score_case(vague, "clarify", {"text": "Which contract?"})["behaviour_ok"]
    assert score_case(vague, "refused", {"text": "x", "citations": [NO_SUPPORT]})["behaviour_ok"]
    assert not score_case(vague, "answer", {"text": "x"})["behaviour_ok"]
    assert score_case(junk, "refused", {"text": "x"})["behaviour_ok"]
    assert not score_case(junk, "clarify", {"text": "Did you mean?"})["behaviour_ok"]


def _result(category, event, ok=True):
    return {"id": "x", "category": category, "event": event, "behaviour_ok": ok, "citation_hit": ok, "numbers_ok": ok}


def test_the_gate_fails_on_any_over_refusal_a_weak_category_or_a_low_overall_rate():
    good = [_result("answerable", "answer")] + [_result(c, "refused") for c in
            ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic") for _ in range(4)]
    assert gate_failures(summarise(good)) == []
    over_refused = [_result("answerable", "refused", ok=False)] + good[1:]
    assert any("over-refusal" in f for f in gate_failures(summarise(over_refused)))
    weak = good[:1] + [_result("nonsense", "answer", ok=False)] * 2 + good[3:]
    failures = gate_failures(summarise(weak))
    assert any(f.startswith("nonsense") for f in failures) and any("overall" in f for f in failures)
```

- [ ] **Step 3: Run them and confirm they fail** — `.../pytest tests/test_golden_scoring.py -q` → `ImportError: cannot import name 'gate_failures'`.

- [ ] **Step 4: Scoring, summary and gate** — in `backend/tests/eval/test_golden.py`:
  - change the module docstring's first line to
    `"""Manual golden-set run against real OpenAI + Pinecone on the live demo configuration (P4 spec §9).`
    and its run line to `Run (from backend/): ENV_FILE=.env.demo $PYDEV/bin/pytest -m eval tests/eval -s"""`;
  - replace `score_case` with:

```python
JUNK = ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic")
EVENT_FOR = {"answer": "answer", "refuse": "refused", "clarify": "clarify"}


def score_case(case: dict, event_type: str, data: dict) -> dict:
    """Pure scoring, unit-tested in tests/test_golden_scoring.py without OpenAI."""
    citations = data.get("citations", [])
    found = numbers_in(data.get("text", ""))
    if case["category"] == "underspecified":  # a clarifying question or a refusal are both acceptable
        behaviour_ok = event_type in ("clarify", "refused")
    else:
        behaviour_ok = event_type == EVENT_FOR[case["expect"]]
    citation_hit = case["expect"] != "answer" or any(
        case["expect_page"] is None or c.get("page") == case["expect_page"] for c in citations
    )
    if case.get("expect_system_notice"):  # explained abstention (N11): only the billing-records reason counts
        behaviour_ok = citation_hit = any(c.get("kind") == "system" and c.get("source") == "billing records"
                                          for c in citations)
    return {"id": case["id"], "category": case["category"], "event": event_type, "behaviour_ok": behaviour_ok,
            "citation_hit": citation_hit,
            "numbers_ok": {_normal(n) for n in case.get("expect_numbers", [])} <= found}


def _rate(results: list[dict], key: str) -> float:
    return sum(r[key] for r in results) / len(results) if results else 1.0


def summarise(results: list[dict]) -> dict:
    graded = [r for r in results if r["category"] in ("answerable", "explained")]
    answerable = [r for r in results if r["category"] == "answerable"]
    junk = [r for r in results if r["category"] in JUNK]
    return {
        "answerable": {key: _rate(graded, key) for key in ("behaviour_ok", "citation_hit", "numbers_ok")},
        "over_refusal": sum(r["event"] != "answer" for r in answerable) / len(answerable) if answerable else 0.0,
        "junk_acceptable": _rate(junk, "behaviour_ok"),
        "junk_by_category": {c: _rate([r for r in junk if r["category"] == c], "behaviour_ok")
                             for c in JUNK if any(r["category"] == c for r in junk)},
    }


def gate_failures(summary: dict) -> list[str]:
    """P4 go/no-go (spec §7.4): no answerable refused, junk >= 90% overall and >= 75% in every category."""
    failures = []
    if summary["over_refusal"] > 0:
        failures.append(f"over-refusal {summary['over_refusal']:.0%} > 0%")
    if summary["junk_acceptable"] < 0.90:
        failures.append(f"junk overall {summary['junk_acceptable']:.0%} < 90%")
    failures += [f"{category} {rate:.0%} < 75%" for category, rate in summary["junk_by_category"].items() if rate < 0.75]
    return failures
```

  - replace `test_golden_set` with:

```python
@pytest.mark.eval
def test_golden_set():
    results = [_run(case) for case in CASES]
    config_hash = eval_config_hash()
    summary = summarise(results)
    REPORTS.mkdir(exist_ok=True)
    relevance = sorted(REPORTS.glob("relevance-*.json"), key=lambda p: p.stat().st_mtime)
    report = REPORTS / f"eval-{config_hash}.json"
    report.write_text(json.dumps({
        "config_hash": config_hash, "chat_model": config.CHAT_MODEL, "min_dense_similarity": config.MIN_DENSE_SIMILARITY,
        "relevance_report": relevance[-1].name if relevance else None, "summary": summary, "results": results,
    }, indent=2))
    print(json.dumps(summary, indent=2), f"\nreport: {report}")
    failures = gate_failures(summary)
    assert not failures, "P4 gate failed: " + "; ".join(failures)
```

- [ ] **Step 5: The threshold in the config hash** — in `backend/app/assistant/graph.py`, `eval_config_hash` returns
  `hashlib.sha256(f"{config.CHAT_MODEL}|{prompt_version()}|{config.EMBEDDING_MODEL}|{config.MIN_DENSE_SIMILARITY}".encode()).hexdigest()[:12]`.

- [ ] **Step 6: The calibration script** — create `backend/scripts/calibrate_relevance.py`:

```python
"""Retrieval-only calibration of MIN_DENSE_SIMILARITY (P4 spec §5). No LLM call; fractions of a cent.
Run from backend/ against the live demo configuration:
  ENV_FILE=.env.demo $PYDEV/bin/python scripts/calibrate_relevance.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.assistant.graph import eval_config_hash  # noqa: E402
from app.assistant.runtime import get_runtime  # noqa: E402
from app.documents import dao as documents_dao  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402
from app.ledger.types import DEMO_TENANT_ID  # noqa: E402
from app.retrieval.search import dense_matches  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
GOLDEN = BACKEND / "tests" / "eval" / "golden.json"
REPORTS = BACKEND / "reports"
JUNK = ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic")
MARGIN = 0.01


def best_dense_score(session, runtime, question: str) -> float | None:
    query = documents_dao.tokenize_known_values(session, DEMO_TENANT_ID, question, config.require("PII_HMAC_KEY"),
                                                config.require("PII_VAULT_KEY"))
    scores = [score for _, score in dense_matches(session, tenant_id=DEMO_TENANT_ID, query=query,
                                                  embeddings=runtime.embeddings, vector_index=runtime.vector_index)]
    return max(scores, default=None)


def main() -> None:
    cases = json.loads(GOLDEN.read_text())
    runtime = get_runtime()
    with SessionLocal() as session:
        rows = [{"id": c["id"], "category": c["category"], "expect": c["expect"], "retrieval": c.get("retrieval", False),
                 "best_dense_score": best_dense_score(session, runtime, c["question"])} for c in cases]
    floor = [r["best_dense_score"] for r in rows if r["retrieval"] and r["best_dense_score"] is not None]
    suggested = round(min(floor) - MARGIN, 3)
    junk = [r for r in rows if r["category"] in JUNK]
    gated = [r for r in junk if r["best_dense_score"] is None or r["best_dense_score"] < suggested]
    for r in sorted(rows, key=lambda r: -(r["best_dense_score"] or 0.0)):
        score = "-" if r["best_dense_score"] is None else f"{r['best_dense_score']:.3f}"
        print(f"{score:>7}  {r['category']:<15} {r['expect']:<8} {r['id']}{'  (sets the floor)' if r['retrieval'] else ''}")
    print(f"\nconfigured MIN_DENSE_SIMILARITY = {config.MIN_DENSE_SIMILARITY}")
    print(f"suggested  MIN_DENSE_SIMILARITY = {suggested}  (lowest floor-setting answerable score - {MARGIN})")
    print(f"junk refused by the retrieval gate alone at the suggestion: {len(gated)}/{len(junk)}")
    REPORTS.mkdir(exist_ok=True)
    report = REPORTS / f"relevance-{eval_config_hash()}.json"
    report.write_text(json.dumps({"configured": config.MIN_DENSE_SIMILARITY, "suggested": suggested, "margin": MARGIN,
                                  "junk_gated": len(gated), "junk_total": len(junk), "cases": rows}, indent=2))
    print(f"report: {report}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run the tests** — `.../pytest tests/test_golden_scoring.py -q` → pass; full suite → no failures. Do **not** run the `eval` test or the calibration script (they cost money and need the demo env; Task 6). Check the script at least imports: `.../python -c "import ast; ast.parse(open('scripts/calibrate_relevance.py').read())"`.

- [ ] **Step 8: Commit** — `git add backend/tests/eval/golden.json backend/tests/eval/test_golden.py backend/tests/test_golden_scoring.py backend/app/assistant/graph.py backend/scripts/calibrate_relevance.py`, then
`git commit -m "test(eval): junk and unanswerable golden cases, an enforced P4 gate and relevance calibration"`.

**REVIEW CHECKPOINT 4.**

---

### Task 5: Frontend clarifying-question card and the end-to-end check

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/screens/Chat.tsx`, `frontend/e2e/demo-approval.e2e.ts`

- [ ] **Step 1: The event type** — in `frontend/src/api.ts`, change the `ChatEvent` member
  `| { type: 'answer' | 'refused'; data: { text: string; citations: Citation[] } }` to
  `| { type: 'answer' | 'refused' | 'clarify'; data: { text: string; citations: Citation[] } }`.

- [ ] **Step 2: The turn outcome** — in `frontend/src/screens/Chat.tsx`:
  - in `type Turn`, change `outcome: 'pending' | 'answer' | 'refused' | 'error';` to
    `outcome: 'pending' | 'answer' | 'refused' | 'clarify' | 'error';`;
  - in the turn rendering, directly before the `{(turn.outcome === 'refused' || turn.outcome === 'error') && (` block, add:

```tsx
                    {turn.outcome === 'clarify' && (
                      <>
                        <AssistantHead label="Clarifying question" variant="neutral" />
                        <Markdown className="chat__prose" text={turn.text} />
                      </>
                    )}
```

  (The existing `onEvent` already sets `outcome: event.type` for every event other than progress/unvalidated/error, and `finally` already focuses the input, so no other change is needed.)

- [ ] **Step 3: End-to-end check** — append to `frontend/e2e/demo-approval.e2e.ts`:

```ts

test('nonsense gets an explicit refusal with a system reason', async ({ page }) => {
  await page.goto('/chat');
  await page.getByLabel('Ask about your indexed contracts').fill('fee fee banana tier tier');
  await page.getByRole('button', { name: 'Send message' }).click();
  await expect(page.getByText('No answer')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/System · indexed contracts/)).toBeVisible();
});
```

  Do **not** run the end-to-end tests: they hit the deployed demo, which only has this code after Task 6.

- [ ] **Step 4: Verify** — from `frontend/`: `npm test` (only the known pre-existing failure), `npm run build`, `npm run lint` (no new findings in the touched files).

- [ ] **Step 5: Commit** — `git add frontend/src/api.ts frontend/src/screens/Chat.tsx frontend/e2e/demo-approval.e2e.ts`, then
`git commit -m "feat(frontend): show a clarifying question as its own card"`.

**REVIEW CHECKPOINT 5.**

---

### Task 6: Calibrate, run the gate, deploy (Claude with the user, not the executor)

1. Calibrate against the live demo configuration: `cd backend && ENV_FILE=.env.demo $PYDEV/bin/python scripts/calibrate_relevance.py`. Read the table; if a floor-setting case sits far below the others, inspect it (the §4 contingency applies only with a failing exact-term case).
2. Set the chosen value in `backend/.env.demo` and in Railway (`MIN_DENSE_SIMILARITY`), and as the default in `backend/app/config.py` with a comment naming the date and the relevance report; commit the code default.
3. Run the gate: `ENV_FILE=.env.demo $PYDEV/bin/pytest -m eval tests/eval/test_golden.py -s`. If it fails on `out_of_corpus` or `false_premise` after the prompt rule, that is the §8 trigger for the sufficiency check (decide together). Other failures: adjust prompt or threshold and re-run.
4. Push; Railway runs migration 0014 only when someone runs it: `./script.demo.sh migrate` (or `script.demo.md` step 3) as `ledger_owner`, then confirm `alembic current` shows `0014_chat_outcome_clarified (head)`.
5. After Railway and Vercel redeploy: `cd frontend && npm run test:e2e` (both tests).
6. Tick P4 in `CHANGELOG.md` with the chosen threshold, the gate numbers and the report names; fix the "3 of 4 per category" wording in the P4 decisions block to "75% per category".

## Definition of done

Tasks 1–5 committed and reviewed; Task 6's calibration report and passing eval gate recorded; migration 0014 applied on Railway; both end-to-end tests green on the deployed demo; P4 ticked.

## Skills that informed the plan

TDD (failing test first in every task); Pragmatic Programmer (crash early: the gate fails the eval loudly, clarifications can't carry figures); Clean Code / DRY (`dense_matches` shared by search and calibration; one refusal mapping); DDIA (the calibration report records the operating point of a derived signal); Clean Architecture (each change sits where its concern already lives).
