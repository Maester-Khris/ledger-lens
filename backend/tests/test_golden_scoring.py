from tests.eval.test_golden import score_case

CASE = {"id": "fund-not-comparable", "expect_page": None, "expect_numbers": [], "expect_refusal": False,
        "expect_system_notice": True}


def test_system_notice_case_passes_only_with_a_system_citation():
    with_notice = score_case(CASE, "refused", {"text": "x", "citations": [{"kind": "system", "detail": "d"}]})
    assert with_notice["refusal_ok"] and with_notice["citation_hit"]
    generic = score_case(CASE, "refused", {"text": "I can't find that", "citations": []})
    assert not generic["refusal_ok"] and not generic["citation_hit"]


def test_ordinary_cases_are_scored_as_before():
    case = {"id": "c", "expect_page": 2, "expect_numbers": ["0.85"], "expect_refusal": False}
    result = score_case(case, "answer", {"text": "0.85%", "citations": [{"kind": "element", "page": 2}]})
    assert result["refusal_ok"] and result["citation_hit"] and result["numbers_ok"]
