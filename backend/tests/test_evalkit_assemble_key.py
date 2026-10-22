"""Chat eval (plan 2026-10-21, Task 6): tiebreak and assembly of the key. Fake clients, no network."""
import json

from scripts.evalkit.assemble_key import assemble, explained_cases, run_tiebreaks, tiebreaker_for
from scripts.evalkit.cases import MIX, Case
from scripts.evalkit.checkpoint import Checkpoint
from scripts.evalkit.providers import DailyBudgetExceeded


def _case(case_id, category="answerable", writer="qwen/qwen3.8-27b", origin="written", **extra):
    base = dict(id=case_id, category=category, question=f"Q {case_id}?", expect="answer", document_key="acme",
                reference="0.75%", expect_numbers=("0.75",), gold_element_ids=("e2",), page=2, writer=writer,
                origin=origin)
    return Case(**(base | extra))


def _agree(case_id, agrees=True):
    return {"case_id": case_id, "agrees": agrees, "reason": "r", "checker": "gemini-4-argon-high"}


def test_tiebreaker_is_the_other_family():
    assert tiebreaker_for("qwen/qwen3.8-27b") == "openai/gpt-oss-20b"
    assert tiebreaker_for("openai/gpt-oss-120b") == "qwen/qwen3.8-27b"


def test_explained_cases_come_from_contracts_without_billing():
    documents = [(f"doc-{i:02d}", f"Fund {i} agreement") for i in range(12, 0, -1)]
    cases = explained_cases(documents, count=10)
    assert len(cases) == 10
    assert cases[0].document_key == "doc-01" and cases[0].question == "Compare the Fund 1 agreement agreement with billing."
    assert {(c.category, c.expect, c.origin, c.writer) for c in cases} == {("explained", "refuse", "data", "data")}


def _tiebreak(tmp_path, disputed, client):
    checkpoint = Checkpoint(tmp_path / "tiebreaks.jsonl", key="case_id")
    clients = {"openai/gpt-oss-20b": client, "qwen/qwen3.8-27b": client}
    return run_tiebreaks(disputed, clients, {"acme": "[e2] p2: fee 0.75%"}, checkpoint), checkpoint


def test_tiebreak_rows_name_the_tiebreaker(tmp_path):
    summary, checkpoint = _tiebreak(tmp_path, [(_case("a"), "wrong page")],
                                    lambda prompt: json.dumps({"keep": True, "reason": "page is right"}))
    assert checkpoint.rows() == [{"case_id": "a", "keep": True, "reason": "page is right",
                                  "tiebreaker": "openai/gpt-oss-20b"}]
    assert summary["kept"] == 1


def test_tiebreak_prompt_carries_the_case_reason_and_text(tmp_path):
    prompts = []
    _tiebreak(tmp_path, [(_case("a"), "wrong page")],
              lambda prompt: prompts.append(prompt) or json.dumps({"keep": False, "reason": "x"}))
    assert "wrong page" in prompts[0] and "[e2] p2:" in prompts[0] and "Q a?" in prompts[0]
    assert "anchor_value" not in prompts[0] and "qwen" not in prompts[0]


def test_unreadable_tiebreak_counts_as_not_kept(tmp_path):
    summary, checkpoint = _tiebreak(tmp_path, [(_case("a"), "r")], lambda prompt: "no idea")
    assert checkpoint.rows()[0]["keep"] is False and summary["unreadable"] == 1


def test_daily_budget_stops_tiebreaks_without_recording(tmp_path):
    def spent(prompt):
        raise DailyBudgetExceeded("spent")
    summary, checkpoint = _tiebreak(tmp_path, [(_case("a"), "r")], spent)
    assert checkpoint.done() == set() and summary["stopped"] == "daily_budget"


def test_rerun_does_not_repeat_tiebreaks(tmp_path):
    calls = []
    client = lambda prompt: calls.append(prompt) or json.dumps({"keep": True, "reason": "x"})
    _tiebreak(tmp_path, [(_case("a"), "r")], client)
    _tiebreak(tmp_path, [(_case("a"), "r"), (_case("b"), "r")], client)
    assert len(calls) == 2


def test_agreed_case_is_kept():
    key, anchors, dropped, _ = assemble([], [_case("a")], {"a": _agree("a")}, {}, [])
    assert [c.id for c in key] == ["a"] and dropped == []


def test_disagreement_won_by_tiebreak_is_kept():
    key, _, dropped, _ = assemble([], [_case("a")], {"a": _agree("a", False)}, {"a": {"case_id": "a", "keep": True}}, [])
    assert [c.id for c in key] == ["a"]


def test_disagreement_lost_is_dropped_and_counted():
    key, _, dropped, summary = assemble([], [_case("a")], {"a": _agree("a", False)},
                                        {"a": {"case_id": "a", "keep": False}}, [])
    assert key == [] and dropped == [{"case_id": "a", "reason": "tiebreak"}]
    assert summary["dropped"] == 1


def test_unchecked_case_is_dropped():
    _, _, dropped, _ = assemble([], [_case("a")], {}, {}, [])
    assert dropped == [{"case_id": "a", "reason": "unchecked"}]


def test_golden_and_explained_cases_are_carried_in():
    golden = _case("fee-schedule", origin="golden", writer="golden")
    explained = _case("x", category="explained", origin="data", writer="data", expect="refuse")
    key, _, _, _ = assemble([golden], [], {}, {}, [explained])
    assert [c.id for c in key] == ["fee-schedule", "x"]


def test_anchor_cases_go_to_their_own_list():
    anchor = _case("anchor:acme:currency#0", origin="anchor", field_path="currency", anchor_value="USD")
    key, anchors, _, _ = assemble([], [anchor], {anchor.id: _agree(anchor.id)}, {}, [])
    assert key == [] and [c.id for c in anchors] == [anchor.id]


def test_summary_counts_per_category():
    cases = [_case("a"), _case("n", category="nonsense", expect="refuse", writer="openai/gpt-oss-120b")]
    _, _, _, summary = assemble([], cases, {"a": _agree("a"), "n": _agree("n")}, {}, [])
    assert summary["categories"]["answerable"] == {"have": 1, "target": MIX["answerable"]}
    assert summary["categories"]["off_topic"] == {"have": 0, "target": MIX["off_topic"]}
    assert summary["writers"] == {"qwen/qwen3.8-27b": 1, "openai/gpt-oss-120b": 1}
    assert summary["key"] == 2


def test_a_groq_daily_limit_error_stops_tiebreaks_without_recording(tmp_path):
    def spent(prompt):
        raise RuntimeError("Error code: 429 - Rate limit reached on tokens per day (TPD): Limit 200000, Used 199000")
    summary, checkpoint = _tiebreak(tmp_path, [(_case("a"), "r")], spent)
    assert summary["stopped"] == "daily_budget" and checkpoint.done() == set()
