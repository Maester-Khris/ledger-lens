from app.assistant.citations import numbers_in, verify_answer

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

