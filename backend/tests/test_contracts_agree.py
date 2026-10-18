"""X1 agree rules (spec section 5): when a second reading of a field counts as the same value."""
from app.contracts.agree import (
    TEXT_SIMILARITY, compare_date, compare_enum, compare_fee_table, compare_field, compare_int, compare_names,
    compare_text, normalise_text,
)

TABLE = [
    {"band_text": "On the first $1,000,000", "rate_text": "0.85%", "up_to_minor": 100_000_000, "rate_bps": "85"},
    {"band_text": "On the next $4,000,000", "rate_text": "0.70%", "up_to_minor": 500_000_000, "rate_bps": "70"},
    {"band_text": "Thereafter", "rate_text": "0.60%", "up_to_minor": None, "rate_bps": "60"},
]


def _bands(*pairs: tuple[str, str]) -> list[dict]:
    return [{"band_text": band, "rate_text": rate} for band, rate in pairs]


def test_fee_table_agrees_across_wording():
    read = _bands(("first $1 million", "85 bps"), ("next $4,000,000", "70 basis points"), ("above", "0.6 %"))
    assert compare_fee_table(TABLE, read).outcome == "agree"


def test_fee_table_rate_off_by_five_bps_disagrees_and_names_band():
    read = _bands(("first $1,000,000", "0.80%"), ("next $4,000,000", "0.70%"), ("thereafter", "0.60%"))
    result = compare_fee_table(TABLE, read)
    assert result.outcome == "disagree"
    assert result.detail is not None and result.detail.startswith("band 1")


def test_fee_table_amount_difference_disagrees_and_names_band():
    read = _bands(("first $1,000,000", "0.85%"), ("next $5,000,000", "0.70%"), ("thereafter", "0.60%"))
    result = compare_fee_table(TABLE, read)
    assert result.outcome == "disagree"
    assert result.detail is not None and result.detail.startswith("band 2")


def test_fee_table_band_count_mismatch_disagrees():
    read = _bands(("first $1,000,000", "0.85%"), ("thereafter", "0.60%"))
    result = compare_fee_table(TABLE, read)
    assert result.outcome == "disagree"
    assert result.detail is not None and "band count" in result.detail


def test_fee_table_unparseable_read_is_unreadable():
    read = _bands(("first $1,000,000", "n/a"), ("next $4,000,000", "0.70%"), ("thereafter", "0.60%"))
    assert compare_fee_table(TABLE, read).outcome == "unreadable"


def test_fee_table_unparseable_extracted_side_disagrees():
    broken = _bands(("first $1,000,000", "see schedule"))
    read = _bands(("first $1,000,000", "0.85%"))
    assert compare_fee_table(broken, read).outcome == "disagree"


def test_text_normalises_case_punctuation_legal_suffix_and_the():
    assert normalise_text("The Acme Capital, L.P.") == normalise_text("acme capital")
    assert normalise_text("Acme  Capital   LLC") == normalise_text("ACME CAPITAL")
    assert normalise_text("Acme Capital Ltd.") == normalise_text("Acme Capital Inc.")


def test_text_agree_exact_after_normalising_and_similar_and_different():
    assert compare_text("Acme Capital Inc.", "ACME CAPITAL").outcome == "agree"
    assert compare_text("Acme Capital Management", "Acme Capital Managment").outcome == "agree"  # OCR typo
    assert compare_text("Acme Capital", "Apex Partners").outcome == "disagree"
    assert TEXT_SIMILARITY == 0.9


def test_null_rules():
    assert compare_field("currency", None, None).outcome == "agree"
    assert compare_field("currency", "USD", None).outcome == "disagree"
    assert compare_field("effective_date", None, "January 1, 2024").outcome == "disagree"
    assert compare_field("fee_tiers", None, None).outcome == "agree"
    assert compare_field("fee_tiers", TABLE, None).outcome == "disagree"


def test_enum_rule():
    assert compare_enum("graduated", "graduated").outcome == "agree"
    assert compare_enum("graduated", "cliff").outcome == "disagree"


def test_date_rule_compares_calendar_dates():
    assert compare_date("January 1, 2024", "2024-01-01").outcome == "agree"
    assert compare_date("1 January 2024", "January 2, 2024").outcome == "disagree"
    assert compare_date("January 1, 2024", "sometime in 2024").outcome == "unreadable"


def test_int_rule():
    assert compare_int(30, 30).outcome == "agree"
    assert compare_int(30, 60).outcome == "disagree"


def test_names_rule_is_a_set_after_normalising():
    assert compare_names(["Jane Doe", "Acme Capital LLC"], ["acme capital", "JANE DOE"]).outcome == "agree"
    assert compare_names(["Jane Doe"], ["Jane Doe", "John Roe"]).outcome == "disagree"


def test_compare_field_dispatches_by_base_name():
    assert compare_field("fee_tiers", TABLE, _bands(("first $1 million", "85 bps"), ("next $4 million", "70 bps"),
                                                    ("thereafter", "60 bps"))).outcome == "agree"
    assert compare_field("fee_method", "graduated", "cliff").outcome == "disagree"
    assert compare_field("payment_timing", "arrears", "arrears").outcome == "agree"
    assert compare_field("agreement_date", "March 3, 2023", "2023-03-03").outcome == "agree"
    assert compare_field("termination_notice_days", 30, 30).outcome == "agree"
    assert compare_field("signatories", ["Jane Doe"], ["JANE DOE"]).outcome == "agree"
    assert compare_field("adviser", "Acme Capital, Inc.", "acme capital").outcome == "agree"
    assert compare_field("governing_law", "Delaware", "New York").outcome == "disagree"


def test_similarity_never_bridges_a_different_number_or_short_word():
    assert compare_text("Acme Growth Fund 2", "Acme Growth Fund 3").outcome == "disagree"
    assert compare_text("Acme Growth Fund I", "Acme Growth Fund II").outcome == "disagree"
    assert compare_text("Acme Growth Fund Class A", "Acme Growth Fund Class B").outcome == "disagree"


def test_int_rule_does_not_coerce():
    assert compare_int(30, 30.9).outcome == "disagree"  # type: ignore[arg-type]
