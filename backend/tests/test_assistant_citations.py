from app.assistant.citations import compose_sections, numbers_in, verify_answer, verify_sections

SOURCES = {"e1": "On the next $1,500,000 the annual rate is 0.85%.", "t1": '{"annual_gap_minor": 40000, "gap": "400.00"}'}


def test_numbers_are_normalised():
    assert numbers_in("0.850% of $1,500,000 over 30 days") == {"0.85", "1500000", "30"}
    assert numbers_in("client <PERSON_1a2b3c4d5e6f> pays") == set()  # token hex is not a number


def test_supported_answer_passes():
    assert verify_answer("Tier 2 is 0.85% on the next $1,500,000.", ["e1"], SOURCES, refused=False) == []
    assert verify_answer("The gap is $400.00 per year.", ["t1"], SOURCES, refused=False) == []


def test_uncited_number_is_a_violation():
    violations = verify_answer("Tier 2 is 0.90%.", ["e1"], SOURCES, refused=False)
    assert violations == ["number 0.9 does not appear in any cited source"]


def test_missing_or_unknown_citations_are_violations():
    assert verify_answer("It is quarterly.", [], SOURCES, refused=False) == ["the answer cites nothing"]
    assert verify_answer("It is quarterly.", ["zz"], SOURCES, refused=False) == ["citation zz was not retrieved in this turn"]


def test_refusal_needs_no_citation():
    assert verify_answer("I can't find that in the indexed contracts.", [], SOURCES, refused=True) == []


def test_reference_numbers_are_not_figures():
    assert numbers_in("Tier 2 under Section 4.2 on p. 3 and § 5") == set()


def test_a_figure_after_a_reference_is_still_checked():
    assert verify_answer("Tier 2 is 2%.", ["e1"], SOURCES, refused=False) == ["number 2 does not appear in any cited source"]


def test_a_clarification_is_not_checked_because_its_text_is_discarded():
    assert verify_answer("Which contract do you mean, Tremblay or Calamos?", [], {}, refused=False, clarification=True) == []
    assert verify_answer("Do you mean the 30-day notice?", [], {}, refused=False, clarification=True) == []
    assert verify_answer("It is 30 days.", [], {}, refused=False) == ["the answer cites nothing"]



def test_an_answer_may_not_assert_that_something_is_absent():
    sources = {"e1": "The annual rate is 1.00% on the first $1,000,000."}
    for claim in ("The Tremblay agreement does not charge a performance fee.",
                  "There is no hurdle rate specified for the fund.", "No hurdle rate applies."):
        assert any("absent" in v for v in verify_answer(claim, ["e1"], sources, refused=False)), claim
    assert verify_answer("The annual rate is 1.00% on the first $1,000,000.", ["e1"], sources, refused=False) == []
    assert verify_answer("The Adviser shall not be liable for losses.", ["e1"], sources, refused=False) == []


def test_a_negative_the_source_states_itself_is_allowed():
    sources = {"e1": "There is no performance fee under this Agreement."}
    assert verify_answer("There is no performance fee under this Agreement.", ["e1"], sources, refused=False) == []


TWO = {"a1": "The annual rate is 1.10% of the first $500 million.", "b1": "The annual rate is 0.55% on the first $500 million."}
CONTRACTS = {"a1": "doc-a", "b1": "doc-b"}


def test_each_section_is_checked_against_its_own_citations_only():
    good = [("The rate is 1.10% of the first $500 million.", ["a1"]), ("The rate is 0.55% on the first $500 million.", ["b1"])]
    assert verify_sections(good, TWO, CONTRACTS) == []
    crossed = [("The rate is 0.55% of the first $500 million.", ["a1"]), good[1]]  # 0.55 is the other contract's rate
    assert verify_sections(crossed, TWO, CONTRACTS) == ["section 1: number 0.55 does not appear in any cited source"]


def test_a_section_must_say_something_cite_something_and_stay_within_one_contract():
    assert verify_sections([("  ", ["a1"])], TWO, CONTRACTS) == ["section 1: it is empty"]
    assert verify_sections([("It is quarterly.", [])], TWO, CONTRACTS) == ["section 1: the answer cites nothing"]
    assert verify_sections([("Both use $500 million.", ["a1", "b1"])], TWO, CONTRACTS) == ["section 1: it cites more than one contract"]


def test_sections_are_rendered_under_the_cited_contracts_title_never_numbered():
    sections = [("The rate is 1.10%.", ["a1"]), ("The rate is 0.55%.", ["b1", "b1"]), ("The gap is 400.00.", ["t1"])]
    text, cited = compose_sections(sections, {"a1": "Calamos notice", "b1": "Voyageur IMA (2025)"})
    assert text == "**Calamos notice**\n\nThe rate is 1.10%.\n\n**Voyageur IMA (2025)**\n\nThe rate is 0.55%.\n\nThe gap is 400.00."
    assert cited == ["a1", "b1", "t1"]
