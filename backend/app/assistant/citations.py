import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from app.documents.redact import TOKEN_PATTERN

NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


REFERENCE_WORD = re.compile(
    r"\b(?:tier|section|clause|paragraph|article|schedule|exhibit|appendix|item|page|p\.)\s*$|§\s*$", re.I
)


def numbers_in(text: str) -> set[str]:
    """Figures only: a number right after a reference word ("Tier 2", "Section 4", "p. 3") names a part of
    the document, it isn't a figure, so it is not checked against sources."""
    cleaned = TOKEN_PATTERN.sub(" ", text)
    found = set()
    for match in NUMBER_PATTERN.finditer(cleaned):
        if REFERENCE_WORD.search(cleaned[:match.start()]):
            continue
        try:
            found.add(format(Decimal(match.group(0).replace(",", "")).normalize(), "f"))
        except InvalidOperation:
            continue
    return found


def verify_answer(text: str, cited_ids: Sequence[str], sources: Mapping[str, str], refused: bool) -> list[str]:
    """Deterministic gate: every number in the answer must appear in something it cites from this turn."""
    if refused:
        return []
    if not cited_ids:
        return ["the answer cites nothing"]
    unknown = [c for c in cited_ids if c not in sources]
    if unknown:
        return [f"citation {c} was not retrieved in this turn" for c in unknown]
    allowed = set().union(*(numbers_in(sources[c]) for c in cited_ids))
    return [f"number {n} does not appear in any cited source" for n in sorted(numbers_in(text) - allowed)]
