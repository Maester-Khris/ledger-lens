import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_starter_question_is_an_answerable_scoped_golden_case():
    """A starter is a promise that the demo answers it, so each one is measured by the eval gate, scoped too."""
    starters = json.loads((ROOT / "frontend/src/lib/starters.json").read_text())
    golden = {case["question"]: case for case in json.loads((ROOT / "backend/tests/eval/golden.json").read_text())}
    for document_key, questions in starters.items():
        for question in questions:
            case = golden.get(question)
            assert case is not None, f"not in golden.json: {question}"
            assert (case["category"], case["expect"], case.get("retrieval"), case.get("scoped")) == ("answerable", "answer", True, True), question
            assert case["expect_document"] == document_key, question
