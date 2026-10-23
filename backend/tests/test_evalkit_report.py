"""Chat eval (plan 2026-10-21, Task 10): the report: rates with margins, failure split, confidence sweep. Pure."""
import pytest

from scripts.evalkit.cases import Case
from scripts.evalkit.report import (anchor_error, confidence_sweep, judge_agreement, metrics, render_markdown)


def _case(case_id, category="answerable", writer="qwen/qwen3.8-27b", gold=("g1",), **extra):
    base = dict(id=case_id, category=category, question=f"Q {case_id}", expect="answer" if category == "answerable" else "refuse",
                reference="r" if category == "answerable" else None, gold_element_ids=gold if category == "answerable" else (),
                writer=writer, origin="written")
    return Case(**(base | extra))


def _row(case_id, event="answer", retrieved=("g1",), confidence=-0.1, behaviour_ok=True):
    return {"case_id": case_id, "event": event, "retrieved": list(retrieved), "confidence": confidence,
            "behaviour_ok": behaviour_ok, "text": "t", "citations": []}


def _judgment(case_id, correct=True, supported=(True,), relevant=(True,)):
    return {"case_id": case_id, "correct": correct, "backend": "cli",
            "statements": [{"text": "s", "supported": s} for s in supported],
            "citations": [{"id": f"c{i}", "relevant": r} for i, r in enumerate(relevant)]}


def test_empty_category_reports_n_zero():
    result = metrics([_case("a1")], {"a1": _row("a1")}, {"a1": _judgment("a1")})
    assert result["refusal_accuracy"]["nonsense"] == {"n": 0, "successes": 0, "rate": None, "low": None, "high": None}


def test_correctness_counts_refused_answerables_as_wrong():
    cases = [_case("a1"), _case("a2")]
    answers = {"a1": _row("a1"), "a2": _row("a2", event="refused")}
    result = metrics(cases, answers, {"a1": _judgment("a1")})
    assert (result["answer_correctness"]["n"], result["answer_correctness"]["successes"]) == (2, 1)
    assert result["over_refusal"]["successes"] == 1


def test_failure_split_uses_retrieved_ids():
    cases = [_case("a1"), _case("a2")]
    answers = {"a1": _row("a1", retrieved=("g1",)), "a2": _row("a2", retrieved=("x",))}
    judgments = {"a1": _judgment("a1", correct=False), "a2": _judgment("a2", correct=False)}
    split = metrics(cases, answers, judgments)["failure_split"]
    assert split == {"generation": 1, "retrieval": 1}


def test_context_recall():
    cases = [_case("a1"), _case("a2")]
    answers = {"a1": _row("a1", retrieved=("g1", "z")), "a2": _row("a2", retrieved=())}
    assert metrics(cases, answers, {})["context_recall"]["successes"] == 1


def test_citation_precision_counts_citations_and_recall_statements():
    cases = [_case("a1")]
    judgments = {"a1": _judgment("a1", supported=(True, False, True), relevant=(True, False))}
    result = metrics(cases, {"a1": _row("a1")}, judgments)
    assert (result["citation_recall"]["successes"], result["citation_recall"]["n"]) == (2, 3)
    assert (result["citation_precision"]["successes"], result["citation_precision"]["n"]) == (1, 2)


def test_refusal_accuracy_per_category_and_overall():
    cases = [_case("n1", category="nonsense"), _case("n2", category="nonsense"), _case("o1", category="off_topic")]
    answers = {"n1": _row("n1", event="refused", behaviour_ok=True), "n2": _row("n2", event="answer", behaviour_ok=False),
               "o1": _row("o1", event="refused", behaviour_ok=True)}
    result = metrics(cases, answers, {})["refusal_accuracy"]
    assert result["nonsense"]["successes"] == 1 and result["off_topic"]["rate"] == 1.0
    assert result["overall"]["n"] == 3 and result["overall"]["successes"] == 2


def test_results_split_by_writer():
    cases = [_case("a1", writer="w1"), _case("a2", writer="w2")]
    answers = {c.id: _row(c.id) for c in cases}
    judgments = {"a1": _judgment("a1"), "a2": _judgment("a2", correct=False)}
    by_writer = metrics(cases, answers, judgments)["by_writer"]
    assert by_writer["w1"]["successes"] == 1 and by_writer["w2"]["successes"] == 0


def test_confidence_sweep_partitions_answers():
    answers = {"a": _row("a", confidence=-0.05), "b": _row("b", confidence=-0.9), "c": _row("c", confidence=-0.5)}
    judgments = {"a": _judgment("a"), "b": _judgment("b", correct=False), "c": _judgment("c")}
    [row] = confidence_sweep(answers, judgments, [-0.3])
    assert row["above"] == {"n": 1, "successes": 1, "rate": 1.0, "low": row["above"]["low"], "high": row["above"]["high"]}
    assert row["below"]["n"] == 2 and row["below"]["successes"] == 1
    assert row["share_below"] == pytest.approx(2 / 3)


def test_judge_agreement_reports_share_and_kappa():
    api = {"a": {"correct": True}, "b": {"correct": False}, "c": {"correct": True}}
    cli = {"a": {"correct": True}, "b": {"correct": True}, "c": {"correct": True}, "z": {"correct": True}}
    result = judge_agreement(api, cli)
    assert result["n"] == 3 and result["agree"] == 2 and result["share"] == pytest.approx(2 / 3)
    assert "kappa" in result


def test_anchor_error_uses_compare_field():
    anchors = [_case("x1", origin="anchor", field_path="billing_frequency", anchor_value="monthly", reference="monthly"),
               _case("x2", origin="anchor", field_path="billing_frequency", anchor_value="quarterly", reference="monthly")]
    result = anchor_error(anchors)
    assert (result["n"], result["errors"]) == (2, 1) and 0 < result["upper_bound"] <= 1


def test_anchor_error_with_no_anchors():
    assert anchor_error([]) == {"n": 0, "errors": 0, "upper_bound": None}


def test_markdown_has_every_rate_with_n_and_margin():
    cases = [_case("a1")]
    report = metrics(cases, {"a1": _row("a1")}, {"a1": _judgment("a1")})
    text = render_markdown(report, anchor={"n": 0, "errors": 0, "upper_bound": None}, agreement=None, sweep=[])
    assert "Answer correctness" in text and "n=1" in text and "95%" in text
