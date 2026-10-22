"""Chat eval (plan 2026-10-21, Task 9): the judge, API and headless Claude Code backends. No model call."""
import json
import subprocess

import pytest

from scripts.evalkit import judge
from scripts.evalkit.cases import Case
from scripts.evalkit.judge import (JUDGE_MODEL, build_input, clean, parse_judgment, run_api, run_cli_batch,
                                   select_sample)

ROW = {"case_id": "c1", "event": "answer", "text": "The fee is 0.75% a year.",
       "citations": [{"id": "e2", "quote": "pays 0.75% a year", "page": 2, "document_id": "d1"}]}


def _case(case_id="c1"):
    return Case(id=case_id, category="answerable", question="What is the fee?", expect="answer", document_key="acme",
                reference="0.75% a year", gold_element_ids=("e2",), writer="qwen/qwen3.8-27b", origin="written",
                anchor_value="SECRET-HUMAN-LABEL")


def _judgment(**extra):
    return {"case_id": "c1", "correct": True, "statements": [{"text": "The fee is 0.75%.", "supported": True}],
            "citations": [{"id": "e2", "relevant": True}]} | extra


def test_judge_model():
    assert JUDGE_MODEL == "claude-sonnet-5-5"


def test_input_has_only_redacted_text_and_no_key_metadata():
    item = build_input(_case(), ROW)
    assert item == {"case_id": "c1", "question": "What is the fee?", "reference": "0.75% a year",
                    "answer": "The fee is 0.75% a year.", "citations": [{"id": "e2", "quote": "pays 0.75% a year"}]}
    assert "SECRET-HUMAN-LABEL" not in json.dumps(item) and "qwen" not in json.dumps(item)


def test_parse_judgment_accepts_a_fenced_reply():
    assert parse_judgment("```json\n" + json.dumps(_judgment()) + "\n```")["correct"] is True


def test_parse_judgment_rejects_a_bad_shape():
    assert parse_judgment("not json") is None
    assert parse_judgment(json.dumps({"case_id": "c1", "correct": "yes"})) is None


def test_unknown_citation_id_is_dropped_and_flagged():
    cleaned = clean(_judgment(citations=[{"id": "e2", "relevant": True}, {"id": "zz", "relevant": True}]), ROW)
    assert cleaned["citations"] == [{"id": "e2", "relevant": True}] and cleaned["judge_inconsistent"] is True


def test_consistent_judgment_is_not_flagged():
    assert clean(_judgment(), ROW)["judge_inconsistent"] is False


def test_sample_is_stable_and_answered_only():
    rows = [{"case_id": c, "event": e} for c, e in
            [("d", "answer"), ("a", "answer"), ("c", "refused"), ("b", "answer")]]
    assert [r["case_id"] for r in select_sample(rows, 2)] == ["a", "b"]
    assert select_sample(rows, 2) == select_sample(list(reversed(rows)), 2)


def test_cli_batch_folder_holds_only_the_batch(tmp_path, monkeypatch):
    seen = {}

    def fake_run(command, cwd=None, capture_output=None, text=None, timeout=None):
        seen.update(command=command, cwd=cwd, files=sorted(p.name for p in cwd.iterdir()))
        reply = {"result": json.dumps({"judgments": [_judgment()]}), "is_error": False}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(reply), stderr="")
    monkeypatch.setattr(judge.subprocess, "run", fake_run)
    out = run_cli_batch([build_input(_case(), ROW)], tmp_path)
    assert [j["case_id"] for j in out] == ["c1"]
    assert seen["files"] == ["batch.jsonl", "instructions.md"] and seen["cwd"] == tmp_path
    command = seen["command"]
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--model") + 1] == JUDGE_MODEL
    assert "--allowedTools" in command or "--disallowedTools" in command


def test_cli_batch_unreadable_output_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(judge.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="oops", stderr=""))
    assert run_cli_batch([build_input(_case(), ROW)], tmp_path) == []


def test_api_backend_refuses_without_yes(capsys):
    with pytest.raises(SystemExit) as stop:
        judge.main(["--run", "r1", "--backend", "api"])
    assert stop.value.code != 0 and "estimate" in capsys.readouterr().out.lower()


def test_api_backend_judges_one_case_per_call():
    class Client:
        def __init__(self):
            self.calls = 0

        def invoke(self, prompt):
            self.calls += 1
            return type("R", (), {"content": json.dumps(_judgment())})()
    client = Client()
    out = run_api([build_input(_case(), ROW)], client)
    assert client.calls == 1 and out[0]["case_id"] == "c1"
