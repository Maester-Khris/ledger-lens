"""Eval case schema, validation rules, and JSONL persistence for the chat evaluation pipeline."""
from collections.abc import Sequence
from dataclasses import asdict, dataclass
import json
from pathlib import Path

CATEGORIES: tuple[str, ...] = (
    "answerable",
    "explained",
    "out_of_corpus",
    "false_premise",
    "underspecified",
    "nonsense",
    "off_topic",
)

MIX: dict[str, int] = {
    "answerable": 190,
    "explained": 10,
    "out_of_corpus": 20,
    "false_premise": 20,
    "underspecified": 20,
    "nonsense": 20,
    "off_topic": 20,
}

EXPECTS: tuple[str, ...] = ("answer", "refuse", "clarify")


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    question: str
    expect: str
    document_key: str | None = None
    reference: str | None = None
    expect_numbers: tuple[str, ...] = ()
    gold_element_ids: tuple[str, ...] = ()
    page: int | None = None
    premise_element_id: str | None = None
    writer: str = ""
    origin: str = "written"
    field_path: str | None = None
    anchor_value: object | None = None


def validate(case: Case) -> list[str]:
    problems: list[str] = []
    if case.category not in CATEGORIES:
        problems.append(f"unknown category: {case.category}")
    if case.expect not in EXPECTS:
        problems.append(f"unknown expect: {case.expect}")
    # The 37 carried-in golden cases predate reference answers and gold passages; the report rates them only where
    # they have them.
    if case.origin != "golden":
        if case.category == "answerable":
            if not case.reference:
                problems.append("answerable case requires a reference answer")
            if not case.gold_element_ids:
                problems.append("answerable case requires gold_element_ids")
        elif case.category == "false_premise":
            if not case.premise_element_id:
                problems.append("false_premise case requires premise_element_id")
        elif case.category == "underspecified":
            if not case.field_path:
                problems.append("underspecified case requires field_path")
    return problems


def from_golden(entry: dict) -> Case:
    return Case(
        id=entry["id"],
        category=entry["category"],
        question=entry["question"],
        expect=entry["expect"],
        document_key=entry.get("expect_document"),
        page=entry.get("expect_page"),
        expect_numbers=tuple(entry.get("expect_numbers", [])),
        writer="golden",
        origin="golden",
    )


def write_cases(path: Path, cases: Sequence[Case]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        for case in cases:
            out.write(json.dumps(asdict(case)) + "\n")


def read_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        raw["expect_numbers"] = tuple(raw.get("expect_numbers", ()))
        raw["gold_element_ids"] = tuple(raw.get("gold_element_ids", ()))
        cases.append(Case(**raw))
    return cases
