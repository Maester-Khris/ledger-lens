import hashlib
import json
import uuid
from collections.abc import Sequence
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.contracts import dao
from app.contracts.fields import ElementRef, evaluate_terms
from app.contracts.schema import SCHEMA_VERSION, ContractTerms
from app.contracts.types import FieldRouting
from app.documents import dao as documents_dao
from app.documents.models import DocumentElement
from app.documents.types import VersionStage

PROMPT = (Path(__file__).parent / "prompts" / "extract_v1.md").read_text()
TEMPERATURE = Decimal(0)


class ExtractionFailed(Exception):
    pass


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def prompt_version() -> str:
    return _sha256(PROMPT)[:12]


def config_hash(model_id: str, parser_version: str) -> str:
    """Everything that changes extraction output. The CI eval gate re-runs the golden set when it changes."""
    parts = [model_id, prompt_version(), SCHEMA_VERSION, parser_version, version("presidio-analyzer")]
    return _sha256(json.dumps(parts))


def render_input(elements: Sequence[DocumentElement]) -> str:
    def attr(value: str) -> str:
        return value.replace('"', "'")

    tags = [
        f'<element id="E{e.ordinal}" page="{e.page_start}" section="{attr(" › ".join(e.section_path))}">{e.text_redacted}</element>'
        for e in elements
    ]
    return "<document>\n" + "\n".join(tags) + "\n</document>"


def call_model(chat_model: BaseChatModel, document_text: str) -> ContractTerms:
    structured = chat_model.with_structured_output(ContractTerms, method="json_schema", include_raw=True)
    messages = [SystemMessage(PROMPT), HumanMessage(document_text)]
    for _attempt in range(2):  # one repair attempt with the validation error, then give up
        result = structured.invoke(messages)
        if result["parsed"] is not None:
            return result["parsed"]
        error = str(result["parsing_error"])
        messages = [*messages, HumanMessage(f"Your output did not match the schema: {error}. Return it again, matching the schema exactly.")]
    raise ExtractionFailed(f"model output did not match the schema twice: {error}")


def run_extraction(session: Session, version_id: uuid.UUID, *, chat_model: BaseChatModel, model_id: str) -> None:
    elements = documents_dao.list_elements(session, version_id)
    detail = documents_dao.parsed_detail(session, version_id)
    session.commit()  # no transaction held open across the model call

    document_text = render_input(elements)
    terms = call_model(chat_model, document_text)
    refs = {f"E{e.ordinal}": ElementRef(e.id, e.text_redacted, e.page_start, e.page_end) for e in elements}
    results = evaluate_terms(terms, refs, detail.get("page_grades", {}))

    run_config = dao.RunConfig(SCHEMA_VERSION, model_id, prompt_version(), TEMPERATURE,
                               config_hash(model_id, detail.get("parser_version", "unknown")), _sha256(document_text))
    run = dao.save_run(session, version_id, run_config, terms.model_dump(mode="json"), results)
    accepted = sum(r.routing is FieldRouting.accepted for r in results)
    documents_dao.append_event(session, version_id, VersionStage.extracted, {
        "run_id": str(run.id), "accepted": accepted, "needs_review": len(results) - accepted,
    })
    session.commit()
