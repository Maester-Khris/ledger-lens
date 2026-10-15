from tests.eval.test_golden import expand, gate_failures, questions, score_case, session_id, summarise

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
    vague, junk = _case("underspecified", "clarify"), _case("off_topic", "refuse")
    assert score_case(vague, "clarify", {"text": "Which contract?"})["behaviour_ok"]
    assert score_case(vague, "refused", {"text": "x", "citations": [NO_SUPPORT]})["behaviour_ok"]
    assert not score_case(vague, "answer", {"text": "x"})["behaviour_ok"]
    assert score_case(junk, "refused", {"text": "x"})["behaviour_ok"]
    assert not score_case(junk, "clarify", {"text": "Did you mean?"})["behaviour_ok"]
    nonsense = _case("nonsense", "refuse")
    assert score_case(nonsense, "clarify", {"text": "What would you like to know?"})["behaviour_ok"]
    assert score_case(nonsense, "refused", {"text": "x", "citations": [NO_SUPPORT]})["behaviour_ok"]
    assert not score_case(nonsense, "answer", {"text": "x"})["behaviour_ok"]


def _result(category, event, ok=True):
    return {"id": "x", "category": category, "event": event, "behaviour_ok": ok, "citation_hit": ok, "numbers_ok": ok}


def test_the_gate_fails_on_any_over_refusal_a_weak_category_or_a_low_overall_rate():
    good = [_result("answerable", "answer")] + [_result(c, "refused") for c in
            ("out_of_corpus", "false_premise", "underspecified", "nonsense", "off_topic") for _ in range(4)]
    assert gate_failures(summarise(good)) == []
    over_refused = [_result("answerable", "refused", ok=False)] + good[1:]
    assert any("over-refusal" in f for f in gate_failures(summarise(over_refused)))
    weak = good[:1] + [_result("nonsense", "answer", ok=False)] * 3 + good[4:]
    failures = gate_failures(summarise(weak))
    assert any(f.startswith("nonsense") for f in failures) and any("overall" in f for f in failures)


def test_a_case_asks_its_setup_questions_first_in_a_session_no_other_run_shares():
    case = {"id": "repeat", "question": "Remind me?", "setup": ["What is the fee?"]}
    assert questions(case) == ["What is the fee?", "Remind me?"]
    assert questions({"id": "plain", "question": "Q?"}) == ["Q?"]
    assert session_id("ab12cd34", case) == "eval-ab12cd34-repeat"
    assert session_id("ffff0000", case) != session_id("ab12cd34", case)


def test_a_scoped_case_is_asked_twice_the_second_time_limited_to_its_document():
    plain = _case("answerable", "answer")
    scoped = _case("answerable", "answer", scoped=True, expect_document="tremblay-ima") | {"id": "fee"}
    assert [(c["id"], c.get("document_key")) for c in expand([plain, scoped])] == [
        ("answerable-answer", None), ("fee", None), ("fee@scoped", "tremblay-ima")]
