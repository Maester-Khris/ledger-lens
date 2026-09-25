RESULT_KEY = "@result"
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from app.ledger.dao import EntryInput

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.documents import dao as documents_dao
from app.governance.dao import InvocationRecord, ModelConfig, record_invocation
from app.retrieval.search import Evidence, search
from app.retrieval.vector_index import VectorIndex


@dataclass
class ToolContext:
    session: Session
    tenant_id: uuid.UUID
    session_id: str
    turn_id: uuid.UUID
    embeddings: Embeddings
    vector_index: VectorIndex
    model: ModelConfig
    hmac_key: str


@dataclass(frozen=True)
class ToolOutcome:
    content: str  # JSON the model reads
    sources: dict[str, str] = field(default_factory=dict)  # citable id -> text the verifier checks numbers against
    citations: dict[str, dict] = field(default_factory=dict)
    result_amount_minor: int | None = None
    result_currency: str | None = None
    proposed_entries: tuple[EntryInput, ...] | None = None  # citable id -> payload the client renders


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[ToolContext, BaseModel], ToolOutcome]
    version: str = "v1"

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.args_model.model_json_schema(),
        }}


def evidence_citation(evidence: Evidence) -> dict:
    return {
        "kind": "element", "document_id": str(evidence.document_id), "document_title": evidence.document_title,
        "version": evidence.version, "page": evidence.page_start, "page_end": evidence.page_end,
        "section": " › ".join(evidence.section_path), "quote": evidence.text,
        "file_url": f"/documents/{evidence.document_id}/versions/{evidence.version}/file#page={evidence.page_start}",
    }


class NoArgs(BaseModel):
    pass


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500, description="What to look for in the contracts")
    document_ids: list[uuid.UUID] | None = Field(default=None, description="Limit to these documents")


def _list_documents(ctx: ToolContext, _args: BaseModel) -> ToolOutcome:
    rows = documents_dao.list_documents(ctx.session, ctx.tenant_id)
    return ToolOutcome(json.dumps([
        {"document_id": str(r.document.id), "document_key": r.document.document_key, "title": r.document.title}
        for r in rows
    ]))


def _search_contracts(ctx: ToolContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, SearchArgs)
    hits = search(ctx.session, tenant_id=ctx.tenant_id, query=args.query, embeddings=ctx.embeddings,
                  vector_index=ctx.vector_index, document_ids=args.document_ids)
    payload = [
        {"id": str(h.element_id), "document": h.document_title, "page": h.page_start,
         "section": " › ".join(h.section_path), "text": h.text, "context": h.context}
        for h in hits
    ]
    return ToolOutcome(
        json.dumps(payload),
        sources={str(h.element_id): h.text for h in hits},
        citations={str(h.element_id): evidence_citation(h) for h in hits},
    )


def default_tools() -> list[ToolSpec]:
    return [
        ToolSpec("list_documents", "List the indexed contracts with their document_id.", NoArgs, _list_documents),
        ToolSpec("search_contracts", "Search contract text. Returns clauses with ids you can cite.", SearchArgs, _search_contracts),
    ]


def execute(spec: ToolSpec, ctx: ToolContext, args: dict) -> ToolOutcome:
    """Validate, tokenise every string argument (a model may echo a client's name), run, and log the call."""
    try:
        raw = spec.args_model.model_validate(args).model_dump()
    except ValidationError as exc:  # model output is untrusted: hand the error back so it can correct the call
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        return ToolOutcome(json.dumps({"error": f"invalid arguments ({problems})"}))
    tokenised = {
        key: documents_dao.tokenize_known_values(ctx.session, ctx.tenant_id, value, ctx.hmac_key) if isinstance(value, str) else value
        for key, value in raw.items()
    }
    parsed = spec.args_model.model_validate(tokenised)
    outcome = spec.run(ctx, parsed)
    invocation = record_invocation(ctx.session, InvocationRecord(
        tenant_id=ctx.tenant_id, session_id=ctx.session_id, tool_name=spec.name, tool_version=spec.version,
        model=ctx.model, input={"turn_id": str(ctx.turn_id), **parsed.model_dump(mode="json")},
        result_amount_minor=outcome.result_amount_minor, result_currency=outcome.result_currency,
        citation={"ids": sorted(k for k in outcome.citations if k != RESULT_KEY)} if outcome.citations else None,
        proposed_entries=outcome.proposed_entries,
    ))
    invocation_id = str(invocation.id)
    return ToolOutcome(
        outcome.content.replace(RESULT_KEY, invocation_id),
        sources={(invocation_id if k == RESULT_KEY else k): v for k, v in outcome.sources.items()},
        citations={(invocation_id if k == RESULT_KEY else k): v | ({"invocation_id": invocation_id} if k == RESULT_KEY else {})
                   for k, v in outcome.citations.items()},
        result_amount_minor=outcome.result_amount_minor, result_currency=outcome.result_currency,
        proposed_entries=outcome.proposed_entries,
    )