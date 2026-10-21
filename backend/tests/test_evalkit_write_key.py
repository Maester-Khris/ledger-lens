"""Chat eval (plan 2026-10-21, Task 4): the Groq writers and the anchor cases. Fake clients, no network."""
import json
import threading
from dataclasses import dataclass

import pytest

from app.contracts import dao
from app.contracts.dao import AdjudicatedLabel, LabelRow
from app.contracts.fields import FieldResult
from app.contracts.types import FieldRouting
from scripts.evalkit.checkpoint import Checkpoint
from scripts.evalkit.providers import DailyBudgetExceeded
from scripts.evalkit.write_key import (JUNK_WRITER, WRITERS, WriteItem, anchor_item, anchor_question, assign_writers,
                                       document_item, document_text, junk_item, parse_anchor, parse_cases, run_writers)
from tests.test_contracts_dao import CONFIG
from tests.test_retrieval_index import parsed_version


@dataclass
class Element:
    id: str
    page_start: int
    text_redacted: str


ELEMENTS = [Element("e1", 1, "This agreement is governed by the laws of Delaware."),
            Element("e2", 2, "The Fund pays the Adviser 0.75% a year of average daily net assets, billed monthly.")]


class NoLimit:
    def acquire(self, tokens: int) -> None:
        pass


class BudgetGone:
    def acquire(self, tokens: int) -> None:
        raise DailyBudgetExceeded("spent")


def _reply(*cases):
    return json.dumps({"cases": list(cases)})


GOOD = {"category": "answerable", "question": "What fee does the Acme Fund pay?", "expect": "answer",
        "reference": "0.75% a year of average daily net assets.", "expect_numbers": ["0.75"],
        "gold_element_ids": ["e2"], "page": 2}


def _item(writer=WRITERS[0], key="acme"):
    return document_item(key, "Acme Fund advisory agreement", ELEMENTS, writer, false_premise=False)


def test_writers_are_the_two_groq_families():
    assert WRITERS == ("qwen/qwen3.8-27b", "openai/gpt-oss-120b")
    assert JUNK_WRITER == "qwen/qwen3.8-27b"


def test_assign_writers_splits_evenly():
    keys = [f"doc-{i:03d}" for i in range(102)]
    assigned = assign_writers(keys)
    assert sorted(assigned) == keys
    assert list(assigned.values()).count(WRITERS[0]) == 51
    assert list(assigned.values()).count(WRITERS[1]) == 51


def test_document_text_lines_carry_ids_and_pages():
    text, ids = document_text(ELEMENTS)
    assert text.splitlines()[1] == "[e2] p2: The Fund pays the Adviser 0.75% a year of average daily net assets, billed monthly."
    assert ids == frozenset({"e1", "e2"})


def test_document_text_is_capped_and_ids_follow_the_cap():
    text, ids = document_text(ELEMENTS, max_chars=60)
    assert "e2" not in ids and "[e2]" not in text
    assert ids == frozenset({"e1"})


def test_document_item_prompt_holds_the_text_and_no_false_premise_rule_by_default():
    item = _item()
    assert item.id == "doc:acme" and item.kind == "document" and item.document_key == "acme"
    assert "[e2] p2:" in item.prompt and "Acme Fund advisory agreement" in item.prompt
    assert "false_premise" not in item.prompt
    assert item.known_element_ids == frozenset({"e1", "e2"})


def test_every_fifth_document_asks_for_a_false_premise():
    item = document_item("acme", "Acme", ELEMENTS, WRITERS[0], false_premise=True)
    assert "false_premise" in item.prompt


def test_junk_item_names_category_count_and_titles():
    item = junk_item("out_of_corpus", JUNK_WRITER, titles=["Acme Fund", "Beta Trust"], fields=["governing_law"])
    assert item.id == "junk:out_of_corpus" and item.kind == "junk" and item.writer == JUNK_WRITER
    assert "out_of_corpus" in item.prompt and "20" in item.prompt and "Beta Trust" in item.prompt


def test_parse_cases_builds_valid_cases_with_stable_ids():
    [case] = parse_cases(_reply(GOOD), item=_item())
    assert case.id == "doc:acme#0"
    assert (case.document_key, case.writer, case.origin) == ("acme", WRITERS[0], "written")
    assert case.gold_element_ids == ("e2",) and case.expect_numbers == ("0.75",)


def test_parse_cases_drops_unknown_element_ids():
    assert parse_cases(_reply(GOOD | {"gold_element_ids": ["e9"]}), item=_item()) == []


def test_parse_cases_drops_invalid_cases():
    assert parse_cases(_reply(GOOD | {"reference": None}), item=_item()) == []


def test_parse_cases_rejects_malformed_json():
    assert parse_cases('{"cases": [ {"category": ', item=_item()) == []
    assert parse_cases("I cannot help with that.", item=_item()) == []


def test_parse_cases_accepts_a_fenced_reply():
    assert len(parse_cases("```json\n" + _reply(GOOD) + "\n```", item=_item())) == 1


def test_junk_cases_need_no_element_ids():
    item = junk_item("nonsense", JUNK_WRITER, titles=["Acme"], fields=[])
    [case] = parse_cases(_reply({"category": "nonsense", "question": "Purple fees sleep loudly?", "expect": "refuse"}),
                         item=item)
    assert case.id == "junk:nonsense#0" and case.document_key is None


def _label():
    return AdjudicatedLabel(document_key="acme", title="Acme Fund advisory agreement", field_path="billing_frequency",
                            value="monthly")


def test_anchor_question_names_the_field_and_contract():
    question = anchor_question("fee_tiers[1]", "Acme Fund advisory agreement")
    assert "fee tiers" in question and "2" in question and "Acme Fund advisory agreement" in question


def test_anchor_item_keeps_the_human_label_out_of_the_prompt():
    label = AdjudicatedLabel(document_key="acme", title="Acme", field_path="governing_law", value="Ontario")
    item = anchor_item(label, ELEMENTS, WRITERS[1])
    assert item.id == "anchor:acme:governing_law" and item.kind == "anchor"
    assert "governing_law" in item.prompt and "[e1] p1:" in item.prompt
    assert "Ontario" not in item.prompt


def test_parse_anchor_keeps_the_label_for_the_report_only():
    item = anchor_item(_label(), ELEMENTS, WRITERS[1])
    case = parse_anchor(json.dumps({"value": "monthly", "gold_element_ids": ["e2"], "page": 2}), item=item)
    assert case.origin == "anchor" and case.field_path == "billing_frequency"
    assert case.reference == "monthly" and case.anchor_value == "monthly"
    assert case.gold_element_ids == ("e2",) and case.writer == WRITERS[1]


def test_parse_anchor_bad_reply_is_none():
    assert parse_anchor("nope", item=anchor_item(_label(), ELEMENTS, WRITERS[1])) is None


def _run(tmp_path, items, clients, limiters=None):
    written, failed = Checkpoint(tmp_path / "candidates.jsonl"), Checkpoint(tmp_path / "failed.jsonl")
    limiters = limiters or {w: NoLimit() for w in WRITERS}
    return run_writers(items, clients, limiters, written, failed), written, failed


def test_written_rows_carry_the_cases(tmp_path):
    summary, written, _ = _run(tmp_path, [_item()], {WRITERS[0]: lambda p: _reply(GOOD), WRITERS[1]: lambda p: ""})
    assert summary["written"] == 1 and summary["failed"] == 0
    [row] = written.rows()
    assert row["id"] == "doc:acme" and row["writer"] == WRITERS[0] and row["kind"] == "document"
    assert row["cases"][0]["id"] == "doc:acme#0"


def test_writer_failure_is_recorded_not_fatal(tmp_path):
    def flaky(prompt):
        if "doc-bad" in prompt:
            raise RuntimeError("boom")
        return _reply(GOOD)
    items = [_item(key="doc-bad"), _item(key="doc-good")]
    summary, written, failed = _run(tmp_path, items, {WRITERS[0]: flaky, WRITERS[1]: flaky})
    assert written.done() == {"doc:doc-good"}
    assert failed.done() == {"doc:doc-bad"}
    assert summary["failed"] == 1


def test_a_malformed_reply_is_retried_once(tmp_path):
    replies = iter(["not json", _reply(GOOD)])
    summary, written, _ = _run(tmp_path, [_item()], {WRITERS[0]: lambda p: next(replies), WRITERS[1]: lambda p: ""})
    assert written.done() == {"doc:acme"}


def test_rerun_skips_written_documents(tmp_path):
    calls = []
    client = lambda p: calls.append(p) or _reply(GOOD)
    items = [_item(key="a"), _item(key="b")]
    _run(tmp_path, items[:1], {WRITERS[0]: client, WRITERS[1]: client})
    calls.clear()
    _run(tmp_path, items, {WRITERS[0]: client, WRITERS[1]: client})
    assert len(calls) == 1 and "(key: b)" in calls[0]


def test_daily_budget_stops_cleanly(tmp_path):
    items = [_item(key="a"), _item(key="b", writer=WRITERS[1])]
    limiters = {WRITERS[0]: BudgetGone(), WRITERS[1]: NoLimit()}
    summary, written, failed = _run(tmp_path, items, {w: lambda p: _reply(GOOD) for w in WRITERS}, limiters)
    assert summary["stopped"] == "daily_budget"
    assert written.done() == {"doc:b"}  # the other writer finished its items
    assert failed.done() == set()       # a budget stop is not a failure: the item is retried on the next run


def test_two_writers_run_concurrently(tmp_path):
    barrier = threading.Barrier(2, timeout=5)

    def client(prompt):
        barrier.wait()  # both writers must be in flight at once, or this times out
        return _reply(GOOD)
    items = [_item(key="a", writer=WRITERS[0]), _item(key="b", writer=WRITERS[1])]
    summary, written, _ = _run(tmp_path, items, {w: client for w in WRITERS})
    assert written.done() == {"doc:a", "doc:b"}


def test_adjudicated_labels_and_accepted_values(db_session, tenant_id):
    version = parsed_version(db_session, tenant_id)
    accepted = [FieldResult("governing_law", "Ontario", [], "q", True, [], "GOOD", FieldRouting.accepted),
                FieldResult("billing_frequency", "monthly", [], "q", True, [], "GOOD", FieldRouting.accepted)]
    run = dao.save_run(db_session, version.id, CONFIG, {}, accepted)
    dao.save_labels(db_session, [LabelRow(run.id, "governing_law", "adjudicated", "Ontario", True),
                                 LabelRow(run.id, "billing_frequency", "judge:x", "monthly", True)])
    db_session.commit()
    labels = dao.adjudicated_labels(db_session, tenant_id)
    assert [(l.field_path, l.value) for l in labels] == [("governing_law", "Ontario")]
    values = dao.accepted_values(db_session, tenant_id)
    assert values["governing_law"] >= {'"Ontario"'} and values["billing_frequency"] >= {'"monthly"'}
