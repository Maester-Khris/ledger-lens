"""Chat eval (plan 2026-10-21, Task 8): the gated final-run runner. Fake `ask`, no model call."""
import pytest

from scripts.evalkit import run_final
from scripts.evalkit.cases import Case
from scripts.evalkit.checkpoint import Checkpoint
from scripts.evalkit.run_final import Reply, answer_row, behaviour_ok, estimate_usd, main, run_cases

TURN = {"answer_redacted": "The fee is 0.75% a year [<PERSON_ab12>].", "input_tokens": 1000, "output_tokens": 50,
        "citations": [{"id": "e2", "quote": "pays 0.75% a year", "page": 2, "document_id": "d1", "kind": "element"}],
        "retrieved": [{"tool": "search_contracts", "id": "e2"}, {"tool": "search_contracts", "id": "e5"}]}


def _case(case_id="c1", category="answerable", **extra):
    base = dict(id=case_id, category=category, question="What is the fee?", expect="answer", document_key="acme",
                reference="0.75%", expect_numbers=("0.75",), gold_element_ids=("e2",), page=2, writer="w", origin="written")
    return Case(**(base | extra))


def _answer(confidence=-0.2):
    return Reply("answer", {"text": "REVEALED real name John Smith, 0.75%", "citations": [], "confidence": confidence}, TURN)


def test_estimate_usd():
    assert estimate_usd(335) == pytest.approx(3.685)


def test_row_text_comes_from_the_stored_turn_not_the_revealed_event():
    row = answer_row(_case(), _answer(), 3.2, False)
    assert row["text"] == TURN["answer_redacted"] and "John Smith" not in str(row)
    assert row["citations"] == [{"id": "e2", "quote": "pays 0.75% a year", "page": 2, "document_id": "d1"}]


def test_row_carries_retrieved_ids_and_confidence():
    row = answer_row(_case(), _answer(-0.4), 3.2, True)
    assert row["retrieved"] == ["e2", "e5"] and row["confidence"] == -0.4 and row["retried"] is True
    assert (row["input_tokens"], row["output_tokens"], row["seconds"]) == (1000, 50, 3.2)


def test_row_scores_behaviour_citation_and_numbers():
    row = answer_row(_case(), _answer(), 1.0, False)
    assert (row["behaviour_ok"], row["citation_hit"], row["numbers_ok"]) == (True, True, True)
    wrong = answer_row(_case(page=9, expect_numbers=("0.80",)), _answer(), 1.0, False)
    assert (wrong["citation_hit"], wrong["numbers_ok"]) == (False, False)


def test_behaviour_ok_accepts_clarify_or_refused_for_nonsense():
    nonsense = _case(category="nonsense", expect="refuse")
    assert behaviour_ok(nonsense, "refused") and behaviour_ok(nonsense, "clarify") and not behaviour_ok(nonsense, "answer")
    assert behaviour_ok(_case(category="out_of_corpus", expect="refuse"), "refused")
    assert not behaviour_ok(_case(category="out_of_corpus", expect="refuse"), "clarify")


def test_a_case_without_a_turn_still_scores():
    row = answer_row(_case(), Reply("refused", {"text": "no", "citations": []}, None), 1.0, False)
    assert row["event"] == "refused" and row["text"] == "no" and row["retrieved"] == []


def _run(tmp_path, cases, ask, slept=None):
    checkpoint = Checkpoint(tmp_path / "answers.jsonl", key="case_id")
    return run_cases(cases, ask, checkpoint, pause=0, sleep=(slept.append if slept is not None else lambda s: None)), checkpoint


def test_resumes_skipping_done_cases(tmp_path):
    asked = []
    ask = lambda case: asked.append(case.id) or _answer()
    _run(tmp_path, [_case("a")], ask)
    asked.clear()
    summary, _ = _run(tmp_path, [_case("a"), _case("b")], ask)
    assert asked == ["b"] and summary["skipped"] == 1


def test_rate_limit_error_is_retried_once(tmp_path):
    replies = iter([Reply("error", {}, None), _answer()])
    slept = []
    _, checkpoint = _run(tmp_path, [_case()], lambda case: next(replies), slept)
    assert checkpoint.rows()[0]["retried"] is True and 65 in slept


def test_second_error_is_recorded_as_error(tmp_path):
    summary, checkpoint = _run(tmp_path, [_case()], lambda case: Reply("error", {}, None))
    assert checkpoint.rows()[0]["event"] == "error" and summary["errors"] == 1


def test_cli_refuses_without_yes(tmp_path, capsys, monkeypatch):
    asked = []
    monkeypatch.setattr(run_final, "load_key", lambda key: [_case()])
    monkeypatch.setattr(run_final, "make_ask", lambda: (lambda case: asked.append(case) or _answer()))
    with pytest.raises(SystemExit) as stop:
        main(["--key", str(tmp_path), "--run", "r1"])
    assert stop.value.code != 0 and asked == []
    assert "estimate" in capsys.readouterr().out.lower()
