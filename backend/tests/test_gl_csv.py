import pytest

from app.ledger.dao import GlCodeTotal
from app.reporting.gl_csv import format_minor, render


@pytest.mark.parametrize(
    ("amount", "units", "expected"),
    [(366_941, 2, "3669.41"), (0, 2, "0.00"), (-1200, 2, "-12.00"), (5, 0, "5"), (7, 3, "0.007")],
)
def test_format_minor(amount, units, expected):
    assert format_minor(amount, units) == expected


def test_render_writes_lines_and_a_balanced_control_row():
    lines = [
        GlCodeTotal("2100", ("Client cash A", "Client cash B"), 366_941, 0, 1),
        GlCodeTotal("4000", ("Advisory Fee Revenue",), 0, 366_941, 1),
    ]
    rendered = render(lines, currency="CAD", minor_units=2)
    assert rendered.content.splitlines() == [
        "gl_code,account_names,currency,debit,credit,net,posting_count",
        "2100,Client cash A; Client cash B,CAD,3669.41,0.00,3669.41,1",
        "4000,Advisory Fee Revenue,CAD,0.00,3669.41,-3669.41,1",
        "TOTAL,,CAD,3669.41,3669.41,0.00,",
    ]
    assert (rendered.line_count, rendered.total_debits_minor, rendered.total_credits_minor) == (2, 366_941, 366_941)
    assert rendered.sha256 == render(lines, currency="CAD", minor_units=2).sha256


def test_render_empty_period_is_header_and_zero_total():
    rendered = render([], currency="CAD", minor_units=2)
    assert rendered.content.splitlines() == [
        "gl_code,account_names,currency,debit,credit,net,posting_count",
        "TOTAL,,CAD,0.00,0.00,0.00,",
    ]


def test_render_refuses_unbalanced_input():
    with pytest.raises(ValueError):
        render([GlCodeTotal("1000", ("x",), 10, 9, 1)], currency="CAD", minor_units=2)