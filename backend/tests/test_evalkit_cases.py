"""Chat eval (plan 2026-10-21, Task 1): the case schema, its JSONL store, checkpoints and Wilson margins. Pure."""
import json
from pathlib import Path

import pytest

from scripts.evalkit.cases import CATEGORIES, MIX, Case, from_golden, read_cases, validate, write_cases
from scripts.evalkit.checkpoint import Checkpoint, summary_line
from scripts.evalkit.stats import rate, wilson

GOLDEN = Path(__file__).parent / "eval" / "golden.json"


def _answerable(**changes) -> Case:
    base = dict(id="c1", category="answerable", question="What is the fee?", expect="answer", document_key="doc-a",
                reference="0.75% a year", expect_numbers=("0.75",), gold_element_ids=("e1",), page=2,
                writer="qwen/qwen3.8-27b", origin="written")
    return Case(**(base | changes))


def test_mix_targets_match_the_spec():
    assert MIX == {"answerable": 190, "explained": 10, "out_of_corpus": 20, "false_premise": 20,
                   "underspecified": 20, "nonsense": 20, "off_topic": 20}
    assert set(MIX) == set(CATEGORIES)


def test_valid_answerable_case_has_no_problems():
    assert validate(_answerable()) == []


def test_answerable_case_needs_reference_and_gold_passages():
    assert len(validate(_answerable(reference=None, gold_element_ids=()))) == 2


def test_false_premise_needs_its_contradicting_passage():
    case = Case(id="f1", category="false_premise", question="Why is the fee 5%?", expect="refuse",
                document_key="doc-a", premise_element_id=None, writer="qwen/qwen3.8-27b", origin="written")
    assert len(validate(case)) == 1


def test_underspecified_needs_its_field_path():
    case = Case(id="u1", category="underspecified", question="What is the fee?", expect="clarify",
                writer="qwen/qwen3.8-27b", origin="written", field_path=None)
    assert len(validate(case)) == 1


def test_unknown_category_is_rejected():
    assert validate(_answerable(category="trivia"))


def test_unknown_expect_is_rejected():
    assert validate(_answerable(expect="maybe"))


def test_golden_case_is_valid_without_reference():
    # The 37 carried-in cases predate gold passages and reference answers; the report rates them only where they have them.
    assert validate(from_golden(json.loads(GOLDEN.read_text())[0])) == []


def test_round_trip_jsonl(tmp_path):
    cases = [_answerable(), _answerable(id="c2", anchor_value={"rate": "0.75"}, field_path="fee_schedule")]
    path = tmp_path / "key.jsonl"
    write_cases(path, cases)
    assert read_cases(path) == cases


def test_from_golden_maps_fee_schedule():
    case = from_golden(json.loads(GOLDEN.read_text())[0])
    assert case.id == "fee-schedule"
    assert case.document_key == "tremblay-ima"
    assert case.page == 2
    assert case.expect_numbers == ("1.00", "0.85", "0.65")
    assert (case.writer, case.origin) == ("golden", "golden")


def test_wilson_interval():
    low, high = wilson(28, 28)
    assert low == pytest.approx(0.879, abs=0.001)
    assert high == pytest.approx(1.0)
    assert wilson(0, 0) is None


def test_rate_with_no_cases():
    result = rate(0, 0)
    assert result["n"] == 0
    assert result["rate"] is None and result["low"] is None and result["high"] is None


def test_rate_reports_successes_and_interval():
    result = rate(9, 10)
    assert (result["n"], result["successes"]) == (10, 9)
    assert result["rate"] == pytest.approx(0.9)
    assert result["low"] < 0.9 < result["high"]


def test_checkpoint_skips_done_keys(tmp_path):
    final = tmp_path / "out.jsonl"
    Checkpoint(final).append({"id": "a", "x": 1})
    assert Checkpoint(final).done() == {"a"}


def test_checkpoint_uses_its_key(tmp_path):
    final = tmp_path / "out.jsonl"
    checkpoint = Checkpoint(final, key="case_id")
    checkpoint.append({"case_id": "q7"})
    assert checkpoint.done() == {"q7"}


def test_checkpoint_ignores_a_torn_last_line(tmp_path):
    final = tmp_path / "out.jsonl"
    checkpoint = Checkpoint(final)
    checkpoint.append({"id": "a"})
    with final.with_suffix(".partial.jsonl").open("a") as out:
        out.write('{"id": "b", "x": ')  # a crash mid-write
    reopened = Checkpoint(final)
    assert reopened.done() == {"a"}
    assert reopened.rows() == [{"id": "a"}]


def test_finish_is_atomic(tmp_path):
    final = tmp_path / "out.jsonl"
    checkpoint = Checkpoint(final)
    checkpoint.append({"id": "a"})
    checkpoint.append({"id": "b"})
    assert checkpoint.finish() == final
    assert [json.loads(line)["id"] for line in final.read_text().splitlines()] == ["a", "b"]
    assert not final.with_suffix(".partial.jsonl").exists()


def test_summary_line_is_one_json_line():
    line = summary_line("write_key", written=3, failed=0)
    assert "\n" not in line
    assert json.loads(line) == {"stage": "write_key", "written": 3, "failed": 0}
