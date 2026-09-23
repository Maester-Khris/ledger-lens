from pathlib import Path

import pytest

from app.documents.markdown import MarkdownElement, render_markdown
from app.documents.parse import numbered_heading, parse_pdf
from app.documents.types import ElementKind

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"


def test_render_markdown_uses_section_depth_for_headings():
    elements = [
        MarkdownElement(ElementKind.heading, ["Agreement"], "Agreement"),
        MarkdownElement(ElementKind.heading, ["Agreement", "3. Fees"], "3. Fees"),
        MarkdownElement(ElementKind.paragraph, ["Agreement", "3. Fees"], "Billed quarterly."),
        MarkdownElement(ElementKind.table, ["Agreement", "3. Fees"], "| a | b |\n|---|---|"),
    ]
    assert render_markdown(elements) == "# Agreement\n\n## 3. Fees\n\nBilled quarterly.\n\n| a | b |\n|---|---|\n"


@pytest.mark.parametrize(
    ("text", "marker", "enumerated", "expected"),
    [
        ("Termination", "4.", True, "4. Termination"),
        ("Governing Law", "5.", True, "5. Governing Law"),
        ("Duties of the Adviser", "(a)", True, "(a) Duties of the Adviser"),
        ("The Adviser shall manage the accounts.", "2.", True, None),  # a sentence: a numbered clause, not a heading
        ("Fees", "•", False, None),  # a bullet, not a numbered section
        ("x" * 81, "1.", True, None),  # too long to be a heading
    ],
)
def test_numbered_heading(text, marker, enumerated, expected):
    assert numbered_heading(text, marker, enumerated) == expected


@pytest.mark.slow
def test_docling_keeps_structure_and_pages():
    parsed = parse_pdf(FIXTURE)
    kinds = {e.kind for e in parsed.elements}
    assert {ElementKind.heading, ElementKind.paragraph, ElementKind.table} <= kinds
    fee_table = next(e for e in parsed.elements if e.kind is ElementKind.table)
    assert fee_table.page_start == 2
    assert "0.85%" in fee_table.text
    termination = next(e for e in parsed.elements if "thirty (30) days" in e.text)
    assert termination.page_start == 1
    # Docling returns numbered headings ("4. Termination") as enumerated list items; parse.py restores them.
    assert termination.section_path == ("Investment Management Agreement", "4. Termination")
    signatures = next(e for e in parsed.elements if "Jean Gagnon" in e.text)
    assert signatures.section_path == ("Signatures",)  # an unnumbered header closes the numbered sections
    assert set(parsed.page_grades) == {1, 2}
    assert all(grade in {"POOR", "FAIR", "GOOD", "EXCELLENT"} for grade in parsed.page_grades.values())
    assert parsed.parser_version.startswith("docling ")
