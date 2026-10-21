"""Chat eval (plan 2026-10-21, Task 5): the Gemini checker in isolated agy batches, and the data checks. No agy run."""
import json
import subprocess
from pathlib import Path

from scripts.evalkit import check_key
from scripts.evalkit.cases import Case, read_cases
from scripts.evalkit.check_key import (CHECKER_MODEL, accept_verdicts, check_batches, data_verdicts, prepare_batch,
                                       run_agy, underspecified_ok)
from scripts.evalkit.checkpoint import Checkpoint


def _case(case_id, category="answerable", key="acme", **extra):
    base = dict(id=case_id, category=category, question=f"Question {case_id}?", expect="answer", document_key=key,
                reference="0.75%", expect_numbers=("0.75",), gold_element_ids=("e2",), page=2,
                writer="qwen/qwen3.8-27b", origin="written")
    return Case(**(base | extra))


def _ok(cases):
    return {"verdicts": [{"case_id": c.id, "agrees": True, "reason": "matches"} for c in cases]}


def test_checker_model():
    assert CHECKER_MODEL == "gemini-4-argon-high"


def test_batch_folder_holds_only_the_batch(tmp_path):
    cases = [_case("a#0"), _case("o#0", category="out_of_corpus", key=None, expect="refuse", reference=None,
                                 expect_numbers=(), gold_element_ids=(), page=None),
             _case("anc#0", origin="anchor", anchor_value="monthly", field_path="billing_frequency")]
    texts = {"acme": "[e2] p2: fee 0.75%", "other": "[x1] p1: unrelated"}
    prepare_batch(cases, tmp_path, texts, {"o#0": "[p9] p3: some passage"}, "INSTRUCTIONS")
    files = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert files == ["batch.jsonl", "documents/acme.txt", "instructions.md", "passages/o#0.txt"]
    rows = [json.loads(line) for line in (tmp_path / "batch.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["a#0", "o#0", "anc#0"]
    for row in rows:  # the checker never sees who wrote a case, nor the human label behind an anchor
        assert "writer" not in row and "anchor_value" not in row
    assert (tmp_path / "instructions.md").read_text() == "INSTRUCTIONS"
    assert str(Path.cwd()) not in (tmp_path / "batch.jsonl").read_text()


def test_run_agy_runs_in_the_batch_folder_without_extra_access(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, cwd=None, capture_output=None, text=None, timeout=None):
        seen.update(command=command, cwd=cwd)
        envelope = {"status": "SUCCESS", "structured_output": {"verdicts": []}, "usage": {"total_tokens": 9}}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(envelope), stderr="")
    monkeypatch.setattr(check_key.subprocess, "run", fake_run)
    schema = tmp_path / "schema.json"
    reply = run_agy(tmp_path, schema)
    assert reply == {"verdicts": []}
    assert seen["cwd"] == tmp_path
    command = seen["command"]
    assert command[0] == "agy" and "--sandbox" in command
    assert command[command.index("--model") + 1] == CHECKER_MODEL
    assert command[command.index("--json-schema") + 1] == str(schema)
    assert "--add-dir" not in command and "--mode" not in command


def test_run_agy_unreadable_output_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(check_key.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="oops", stderr="err"))
    assert run_agy(tmp_path, tmp_path / "s.json") == {}


def test_accept_verdicts_matches_every_case():
    cases = [_case("a"), _case("b")]
    assert [v["case_id"] for v in accept_verdicts(cases, _ok(cases))] == ["a", "b"]


def test_missing_case_rejects_the_batch():
    cases = [_case("a"), _case("b")]
    assert accept_verdicts(cases, _ok(cases[:1])) is None


def test_unknown_case_id_rejects_the_batch():
    cases = [_case("a")]
    reply = _ok(cases)
    reply["verdicts"].append({"case_id": "zzz", "agrees": True, "reason": "x"})
    assert accept_verdicts(cases, reply) is None


def test_malformed_verdict_rejects_the_batch():
    assert accept_verdicts([_case("a")], {"verdicts": [{"case_id": "a", "agrees": "yes"}]}) is None
    assert accept_verdicts([_case("a")], {}) is None


def _check(tmp_path, cases, runner, batch_size=2):
    verdicts, failed = Checkpoint(tmp_path / "verdicts.jsonl", key="case_id"), Checkpoint(tmp_path / "check_failed.jsonl")
    return check_batches(cases, runner, verdicts, failed, batch_size), verdicts, failed


def test_verdict_rows_name_the_checker(tmp_path):
    summary, verdicts, _ = _check(tmp_path, [_case("a")], _ok)
    [row] = verdicts.rows()
    assert row == {"case_id": "a", "agrees": True, "reason": "matches", "checker": CHECKER_MODEL}
    assert summary["checked"] == 1 and summary["failed_batches"] == 0


def test_rejected_batch_is_retried_once(tmp_path):
    replies = iter([{}, None])

    def runner(batch):
        reply = next(replies)
        return _ok(batch) if reply is None else reply
    _, verdicts, _ = _check(tmp_path, [_case("a")], runner)
    assert verdicts.done() == {"a"}


def test_twice_rejected_batch_is_recorded(tmp_path):
    summary, verdicts, failed = _check(tmp_path, [_case("a"), _case("b"), _case("c")], lambda batch: {})
    assert verdicts.done() == set()
    assert summary["failed_batches"] == 2
    assert sorted(case_id for row in failed.rows() for case_id in row["case_ids"]) == ["a", "b", "c"]


def test_rerun_batches_only_unchecked_cases(tmp_path):
    cases = [_case("a"), _case("b"), _case("c")]
    _check(tmp_path, cases[:2], _ok)
    sent = []
    _check(tmp_path, cases, lambda batch: sent.append([c.id for c in batch]) or _ok(batch))
    assert sent == [["c"]]


def test_underspecified_needs_two_values():
    values = {"governing_law": {'"Delaware"', '"Ontario"'}, "currency": {'"USD"'}}
    assert underspecified_ok(values, "governing_law") is True
    assert underspecified_ok(values, "currency") is False
    assert underspecified_ok(values, "fee_method") is False


def test_data_verdicts_cover_underspecified_cases_only():
    cases = [_case("u1", category="underspecified", key=None, expect="clarify", field_path="governing_law",
                   reference=None, expect_numbers=(), gold_element_ids=()),
             _case("u2", category="underspecified", key=None, expect="clarify", field_path="currency",
                   reference=None, expect_numbers=(), gold_element_ids=()),
             _case("a")]
    rows = data_verdicts(cases, {"governing_law": {'"Delaware"', '"Ontario"'}, "currency": {'"USD"'}})
    assert [(r["case_id"], r["agrees"], r["checker"]) for r in rows] == [("u1", True, "data"), ("u2", False, "data")]
