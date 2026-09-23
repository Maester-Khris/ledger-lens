from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

from app.documents.types import ElementKind

GRADES = ("POOR", "FAIR", "GOOD", "EXCELLENT")


@dataclass(frozen=True)
class ParsedElement:
    kind: ElementKind
    text: str
    section_path: tuple[str, ...]
    page_start: int
    page_end: int


@dataclass(frozen=True)
class ParsedDocument:
    elements: tuple[ParsedElement, ...]
    page_grades: dict[int, str]
    parser_version: str


@lru_cache(maxsize=1)
def _converter():
    from docling.document_converter import DocumentConverter

    return DocumentConverter()  # loads layout/table models once per process


def _grade(value: object) -> str:
    name = getattr(value, "name", str(value)).upper()
    return name if name in GRADES else "POOR"  # an unknown grade is treated as the worst case


def parse_pdf(path: Path) -> ParsedDocument:
    from docling_core.types.doc import DocItemLabel, TableItem

    heading_labels = {DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER}
    text_labels = {DocItemLabel.TEXT, DocItemLabel.PARAGRAPH, DocItemLabel.LIST_ITEM, DocItemLabel.CAPTION}

    result = _converter().convert(str(path))
    document = result.document
    stack: list[tuple[int, str]] = []  # (heading level, heading text)
    elements: list[ParsedElement] = []
    for item, _depth in document.iterate_items():
        pages = [prov.page_no for prov in getattr(item, "prov", [])] or [1]
        if item.label in heading_labels:
            level = 0 if item.label is DocItemLabel.TITLE else getattr(item, "level", 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, item.text.strip()))
            kind, text = ElementKind.heading, item.text.strip()
        elif isinstance(item, TableItem):
            kind, text = ElementKind.table, item.export_to_markdown(doc=document).strip()
        elif item.label in text_labels:
            kind, text = ElementKind.paragraph, item.text.strip()
        else:
            continue  # page headers/footers, pictures: not citable content
        if text:
            elements.append(ParsedElement(kind, text, tuple(t for _, t in stack), min(pages), max(pages)))

    # Docling keys pages by 0-based integer index; check once and adjust if already 1-based
    raw_pages = result.confidence.pages
    keys_int = [int(k) for k in raw_pages.keys()]
    offset = 0 if (keys_int and min(keys_int) == 1) else 1
    page_grades = {
        int(index) + offset: _grade(scores.mean_grade)
        for index, scores in raw_pages.items()
    }
    return ParsedDocument(tuple(elements), page_grades, f"docling {version('docling')}")
