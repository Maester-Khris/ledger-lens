"""Chat eval (plan 2026-10-21, Task 7): the retrieval threshold sweep, top-k recall and context recall. Pure."""
import pytest

from scripts.evalkit.cases import Case
from scripts.evalkit.sweep import THRESHOLDS, sweep, topk_recall, score_case


def _case(case_id, category="answerable", gold=("g1",), **extra):
    base = dict(id=case_id, category=category, question="Q?", expect="answer" if category == "answerable" else "refuse",
                reference="r" if category == "answerable" else None, gold_element_ids=gold if category == "answerable" else (),
                writer="w", origin="written")
    return Case(**(base | extra))


def test_thresholds_cover_038_to_050():
    assert THRESHOLDS[0] == 0.38 and THRESHOLDS[-1] == 0.50 and len(THRESHOLDS) == 13
    assert THRESHOLDS[1] == 0.39


def test_score_case_reports_best_gold_scores_and_rank():
    matches = [("a", 0.61), ("g1", 0.55), ("b", 0.40)]
    assert score_case(matches, _case("c1")) == {"best": 0.61, "gold_scores": [0.55], "gold_rank": 2}


def test_score_case_with_no_matches():
    assert score_case([], _case("c1")) == {"best": None, "gold_scores": [None], "gold_rank": None}


def test_score_case_takes_the_first_gold_in_rank_order():
    matches = [("g2", 0.7), ("g1", 0.6)]
    assert score_case(matches, _case("c1", gold=("g1", "g2")))["gold_rank"] == 1


def _rows(**scores):
    return {k: dict(best=v[0], gold_scores=v[1], gold_rank=v[2]) for k, v in scores.items()}


def test_answerable_is_gated_below_its_best_score():
    cases = [_case("a1")]
    rows = _rows(a1=(0.44, [0.44], 1))
    at_043, at_046 = (next(r for r in sweep(rows, cases, THRESHOLDS) if r["threshold"] == t) for t in (0.43, 0.46))
    assert at_043["answerable_gated"] == 0 and at_046["answerable_gated"] == 1


def test_gold_is_cut_when_every_gold_score_is_below():
    cases = [_case("a1")]
    rows = _rows(a1=(0.60, [0.41], 3))  # something answers, but not the gold passage
    result = {r["threshold"]: r for r in sweep(rows, cases, THRESHOLDS)}
    assert result[0.40]["gold_cut"] == 0 and result[0.42]["gold_cut"] == 1
    assert result[0.42]["answerable_gated"] == 0


def test_gold_missing_from_candidates_is_cut_at_every_threshold():
    cases = [_case("a1")]
    rows = _rows(a1=(0.60, [None], None))
    assert all(r["gold_cut"] == 1 for r in sweep(rows, cases, THRESHOLDS))


def test_junk_goes_through_when_a_passage_reaches_the_threshold():
    cases = [_case("j1", category="out_of_corpus"), _case("j2", category="nonsense")]
    rows = _rows(j1=(0.456, [], None), j2=(None, [], None))
    result = {r["threshold"]: r for r in sweep(rows, cases, THRESHOLDS)}
    assert result[0.45]["junk_through"] == 1 and result[0.46]["junk_through"] == 0
    assert result[0.45]["junk_n"] == 2


def test_sweep_counts_denominators():
    cases = [_case("a1"), _case("a2", gold=()), _case("j1", category="off_topic")]
    rows = _rows(a1=(0.5, [0.5], 1), a2=(0.5, [], 1), j1=(0.3, [], None))
    first = sweep(rows, cases, THRESHOLDS)[0]
    assert (first["answerable_n"], first["gold_n"], first["junk_n"]) == (2, 1, 1)


def test_topk_recall_counts_rank():
    cases = [_case("a1")]
    rows = _rows(a1=(0.5, [0.5], 6))
    assert topk_recall(rows, cases, 5)["rate"] == 0.0
    assert topk_recall(rows, cases, 8)["rate"] == 1.0


def test_topk_recall_without_gold_cases_reports_n_zero():
    assert topk_recall({}, [_case("j1", category="nonsense")], 5)["n"] == 0
