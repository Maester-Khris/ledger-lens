from collections.abc import Sequence
from dataclasses import dataclass

from app.documents.types import ElementKind

MAX_HEADING_DEPTH = 6


@dataclass(frozen=True)
class MarkdownElement:
    kind: ElementKind
    section_path: Sequence[str]
    text: str


def render_markdown(elements: Sequence[MarkdownElement]) -> str:
    """The markdown view is derived, never stored: document_elements are the record."""
    blocks = []
    for element in elements:
        if element.kind is ElementKind.heading:
            depth = min(max(len(element.section_path), 1), MAX_HEADING_DEPTH)
            blocks.append(f"{'#' * depth} {element.text}")
        else:
            blocks.append(element.text)
    return "\n\n".join(blocks) + "\n"
