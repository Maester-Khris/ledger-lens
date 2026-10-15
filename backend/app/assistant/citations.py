import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from app.documents.redact import TOKEN_PATTERN

NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")


REFERENCE_WORD = re.compile(
    r"\b(?:tier|section|clause|paragraph|article|schedule|exhibit|appendix|item|page|p\.)\s*$|§\s*$", re.I
)

# An answer may not assert that something is absent ("does not charge a performance fee"): a source not mentioning
# a thing is not evidence about it (P4 D10). ponytail: a pattern list, so a rephrasing can slip through; the
# upgrade path is the LLM sufficiency check in spec §8.
ABSENCE_CLAIM = re.compile(
    r"\b(?:does|do|did)\s+not\s+(?:charge|specify|mention|include|provide|contain|state|have|apply|address|set|impose)\b"
    r"|\bthere\s+(?:is|are)\s+no\b"
    r"|\bno\s+[\w\s-]{1,40}?\b(?:is|are)\s+(?:specified|mentioned|stated|provided|charged|addressed|defined|set)\b"
    r"|\bno\s+[\w\s-]{1,40}?\bappl(?:y|ies)\b"
    r"|\b(?:is|are)\s+not\s+(?:specified|mentioned|stated|provided|addressed|defined|charged)\b",
    re.I,
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


def verify_answer(text: str, cited_ids: Sequence[str], sources: Mapping[str, str], refused: bool,
                  clarification: bool = False) -> list[str]:
    """Deterministic gate: every number in the answer must appear in something it cites from this turn.
    A clarifying question's text is written by the service, so it is not checked."""
    if refused:
        return []
    if clarification:
        return []
    if not cited_ids:
        return ["the answer cites nothing"]
    unknown = [c for c in cited_ids if c not in sources]
    if unknown:
        return [f"citation {c} was not retrieved in this turn" for c in unknown]
    cited_text = " ".join(sources[c] for c in cited_ids).lower()
    absent = [m.group(0) for m in ABSENCE_CLAIM.finditer(text) if m.group(0).lower() not in cited_text]
    allowed = set().union(*(numbers_in(sources[c]) for c in cited_ids))
    return ([f"number {n} does not appear in any cited source" for n in sorted(numbers_in(text) - allowed)]
            + [f'"{phrase}" says something is absent, which no cited source states; refuse instead' for phrase in absent])


def verify_sections(sections: Sequence[tuple[str, Sequence[str]]], sources: Mapping[str, str],
                    contracts: Mapping[str, str | None]) -> list[str]:
    """A per-contract answer: each section is checked on its own, against its own citations only, so a figure from
    one contract can't be backed by a passage from another. `contracts` maps a citable id to its document."""
    violations = []
    for position, (text, cited) in enumerate(sections, start=1):
        problems = ["it is empty"] if not text.strip() else verify_answer(text, cited, sources, refused=False)
        if not problems and len({contracts.get(c) for c in cited}) > 1:
            problems = ["it cites more than one contract"]
        violations += [f"section {position}: {problem}" for problem in problems]
    return violations


def compose_sections(sections: Sequence[tuple[str, Sequence[str]]], titles: Mapping[str, str | None]) -> tuple[str, list[str]]:
    """The answer text and its citations, built from verified sections. Each heading is the cited contract's title,
    taken from the record, not from the model: it writes no list numbering and no contract names."""
    parts = []
    for text, cited in sections:
        title = titles.get(cited[0])
        parts.append(f"**{title}**\n\n{text}" if title else text)
    return "\n\n".join(parts), list(dict.fromkeys(c for _, cited in sections for c in cited))
