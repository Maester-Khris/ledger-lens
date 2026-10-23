"""Chat eval (plan 2026-10-21, Task 5): the Gemini checker in isolated agy batches, and the data checks. No agy run."""
import json
import subprocess
import threading
from collections import Counter
from pathlib import Path

import pytest

from scripts.evalkit import check_key
from scripts.evalkit.cases import Case, read_cases
from scripts.evalkit.check_key import (CHECKER_MODEL, CLAUDE_EFFORT, CLAUDE_MODEL, MEDIUM_MODEL, accept_verdicts,
                                       check_batches, checker_label, data_verdicts, parse_args, passage_cases,
                                       prepare_batch, run_agy, run_claude, underspecified_ok)
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


def test_run_agy_says_why_a_call_failed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_key.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="oops", stderr="boom"))
    assert run_agy(tmp_path, tmp_path / "s.json") == {}
    assert "boom" in capsys.readouterr().err


def test_run_agy_says_when_a_call_timed_out(tmp_path, monkeypatch, capsys):
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)
    monkeypatch.setattr(check_key.subprocess, "run", slow)
    assert run_agy(tmp_path, tmp_path / "s.json") == {}
    assert "timed out" in capsys.readouterr().err


def test_run_agy_keeps_complete_verdicts_from_an_error_envelope(tmp_path, monkeypatch):
    # agy reported "stream was interrupted" yet still delivered every verdict (seen live on a slow high-effort batch)
    envelope = {"status": "ERROR", "error": "The stream was interrupted.", "structured_output": {"verdicts": [1]}}
    monkeypatch.setattr(check_key.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(envelope), stderr=""))
    assert run_agy(tmp_path, tmp_path / "s.json") == {"verdicts": [1]}


def test_run_agy_uses_the_given_model_and_timeout(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(command=command, timeout=kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"structured_output": {}}), stderr="")
    monkeypatch.setattr(check_key.subprocess, "run", fake_run)
    run_agy(tmp_path, tmp_path / "s.json", model=MEDIUM_MODEL, timeout=77)
    command = seen["command"]
    assert command[command.index("--model") + 1] == MEDIUM_MODEL
    assert command[command.index("--print-timeout") + 1] == "77s"
    assert seen["timeout"] > 77


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


def _check(tmp_path, cases, runner, batch_size=2, **options):
    verdicts, failed = Checkpoint(tmp_path / "verdicts.jsonl", key="case_id"), Checkpoint(tmp_path / "check_failed.jsonl")
    return check_batches(cases, runner, verdicts, failed, batch_size, **options), verdicts, failed


def test_models_and_defaults():
    assert MEDIUM_MODEL == "gemini-4-argon-medium"
    args = parse_args(["--key", "k", "--backend", "agy"])
    assert (args.model, args.batch_size, args.workers, args.timeout) == (CHECKER_MODEL, 10, 3, 1500)
    assert parse_args(["--key", "k", "--backend", "agy", "--medium"]).model == MEDIUM_MODEL
    assert parse_args(["--key", "k", "--backend", "agy", "--model", "x"]).model == "x"
    with pytest.raises(SystemExit):
        parse_args(["--key", "k", "--medium", "--model", "x"])


def test_claude_is_the_default_checker_at_medium_effort():
    # Gemini's quota ended, and a free-model sweep showed only a long-reasoning model rejects; Opus at medium passed
    # the negative controls (20 of 20 corrupted cases rejected, 0 of 10 intact ones) and is the settled checker
    assert (CLAUDE_MODEL, CLAUDE_EFFORT) == ("claude-opus-5-5", "medium")
    args = parse_args(["--key", "k"])
    assert (args.backend, args.model, args.effort) == ("claude", CLAUDE_MODEL, CLAUDE_EFFORT)
    assert parse_args(["--key", "k", "--effort", "max"]).effort == "max"
    assert parse_args(["--key", "k", "--model", "claude-sonnet-5-5"]).model == "claude-sonnet-5-5"
    with pytest.raises(SystemExit):
        parse_args(["--key", "k", "--effort", "extreme"])


def test_checker_label_names_the_effort_only_where_it_applies():
    assert checker_label("claude", CLAUDE_MODEL, "medium") == "claude-opus-5-5@medium"
    assert checker_label("agy", CHECKER_MODEL, "medium") == CHECKER_MODEL


def _claude_folder(tmp_path):
    cases = [_case("a#0"), _case("o#0", category="out_of_corpus", key=None, expect="refuse", reference=None,
                                 expect_numbers=(), gold_element_ids=(), page=None)]
    instructions = "Read the files. Read only the files in this folder."
    prepare_batch(cases, tmp_path, {"acme": "[e2] p2: fee 0.75%"}, {"o#0": "[p9] p3: some passage"}, instructions)
    return tmp_path


def _claude_reply(monkeypatch, envelope, seen=None):
    def fake_run(command, **kwargs):
        if seen is not None:
            seen.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(envelope), stderr="")
    monkeypatch.setattr(check_key.subprocess, "run", fake_run)


def test_run_claude_is_isolated_and_sends_the_files_inline(tmp_path, monkeypatch):
    folder, seen = _claude_folder(tmp_path), {}
    _claude_reply(monkeypatch, {"is_error": False, "result": json.dumps({"verdicts": []})}, seen)
    run_claude(folder, model=CLAUDE_MODEL, effort="medium", timeout=77)
    command, prompt = seen["command"], seen["command"][2]
    assert command[:2] == ["claude", "-p"] and seen["cwd"] == folder and seen["timeout"] == 77
    assert command[command.index("--model") + 1] == CLAUDE_MODEL
    assert command[command.index("--effort") + 1] == "medium"
    for flag in ("--system-prompt", "--disable-slash-commands", "--strict-mcp-config", "--disallowedTools"):
        assert flag in command  # same isolation as the judge: no operator CLAUDE.md, skills, MCP or tools
    assert "fee 0.75%" in prompt and "some passage" in prompt and '"id": "a#0"' in prompt
    assert "Read only the files in this folder" not in prompt  # there is no folder to read from the model's side


def test_run_claude_reads_a_fenced_reply(tmp_path, monkeypatch):
    verdicts = {"verdicts": [{"case_id": "a#0", "agrees": True, "reason": "ok"}]}
    _claude_reply(monkeypatch, {"is_error": False, "result": "```json\n" + json.dumps(verdicts) + "\n```"})
    assert run_claude(_claude_folder(tmp_path)) == verdicts


def test_run_claude_says_why_a_call_failed(tmp_path, monkeypatch, capsys):
    folder = _claude_folder(tmp_path)
    _claude_reply(monkeypatch, {"is_error": True, "result": "usage limit reached"})
    assert run_claude(folder) == {}
    assert "usage limit reached" in capsys.readouterr().err
    monkeypatch.setattr(check_key.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="oops", stderr="boom"))
    assert run_claude(folder) == {}
    assert "boom" in capsys.readouterr().err
    _claude_reply(monkeypatch, {"is_error": False, "result": "no json here"})
    assert run_claude(folder) == {}
    assert "not JSON" in capsys.readouterr().err


def test_run_claude_says_when_a_call_timed_out(tmp_path, monkeypatch, capsys):
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)
    monkeypatch.setattr(check_key.subprocess, "run", slow)
    assert run_claude(_claude_folder(tmp_path)) == {}
    assert "timed out" in capsys.readouterr().err


def test_verdict_rows_name_the_model_used(tmp_path):
    _, verdicts, _ = _check(tmp_path, [_case("a")], _ok, checker=MEDIUM_MODEL)
    assert [row["checker"] for row in verdicts.rows()] == [MEDIUM_MODEL]


def test_batches_run_side_by_side_when_workers_are_given(tmp_path):
    barrier = threading.Barrier(2, timeout=5)  # both batches must be inside the runner at once

    def runner(batch):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            return {}
        return _ok(batch)
    summary, verdicts, _ = _check(tmp_path, [_case("a"), _case("b")], runner, batch_size=1, workers=2)
    assert verdicts.done() == {"a", "b"} and summary["failed_batches"] == 0


def test_parallel_batches_keep_one_retry_and_the_record_of_failures(tmp_path):
    calls, lock = Counter(), threading.Lock()

    def runner(batch):
        with lock:
            calls[batch[0].id] += 1
        return {} if batch[0].id == "bad" else _ok(batch)
    cases = [_case("a"), _case("bad"), _case("b"), _case("c")]
    summary, verdicts, failed = _check(tmp_path, cases, runner, batch_size=1, workers=3)
    assert verdicts.done() == {"a", "b", "c"} and calls["bad"] == 2
    assert summary == {"checked": 3, "failed_batches": 1, "skipped": 0}
    assert [row["case_ids"] for row in failed.rows()] == [["bad"]]
    assert len(verdicts.rows()) == 3  # each verdict written once


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


def test_passages_are_only_fetched_for_unchecked_out_of_corpus_cases():
    out = dict(category="out_of_corpus", key=None, expect="refuse", reference=None, expect_numbers=(),
               gold_element_ids=(), page=None)
    cases = [_case("o1", **out), _case("o2", **out), _case("a")]
    assert [c.id for c in passage_cases(cases, done={"o1"})] == ["o2"]
