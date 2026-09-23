import json
import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.assistant.tools import RESULT_KEY, ToolContext, ToolOutcome, ToolSpec
from app.contracts import dao as contracts_dao
from app.contracts.compare import compare_contract_to_billing, comparison_to_json
from app.contracts.errors import ContractNotComparable
from app.retrieval import dao as retrieval_dao


class FieldsArgs(BaseModel):
    document_id: uuid.UUID = Field(description="From list_documents")


class CompareArgs(BaseModel):
    document_id: uuid.UUID = Field(description="From list_documents")
    as_of: date | None = Field(default=None, description="Valuation date; omit for the latest")


def _element_sources(ctx: ToolContext, element_ids: set[uuid.UUID]) -> tuple[dict[str, str], dict[str, dict]]:
    sources, citations = {}, {}
    for element, version, document in retrieval_dao.evidence_rows(ctx.session, list(element_ids)).values():
        sources[str(element.id)] = element.text_redacted
        citations[str(element.id)] = {
            "kind": "element", "document_id": str(document.id), "document_title": document.title,
            "version": version.version, "page": element.page_start, "page_end": element.page_end,
            "section": " › ".join(element.section_path), "quote": element.text_redacted,
            "file_url": f"/documents/{document.id}/versions/{version.version}/file#page={element.page_start}",
        }
    return sources, citations


def _get_contract_fields(ctx: ToolContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, FieldsArgs)
    served = contracts_dao.served_fields(ctx.session, ctx.tenant_id, args.document_id)
    if served is None:
        return ToolOutcome(json.dumps({"error": "This contract hasn't been extracted yet."}))
    element_ids = {i for f in served.fields.values() for i in f.element_ids}
    sources, citations = _element_sources(ctx, element_ids)
    body = {
        "fields": {path: f.value for path, f in served.fields.items()},
        "cite": {path: [str(i) for i in f.element_ids] for path, f in served.fields.items()},
        "not_validated": served.unserved,
    }
    return ToolOutcome(json.dumps(body), sources=sources, citations=citations)


def _compare(ctx: ToolContext, args: BaseModel) -> ToolOutcome:
    assert isinstance(args, CompareArgs)
    try:
        comparison = compare_contract_to_billing(ctx.session, tenant_id=ctx.tenant_id, document_id=args.document_id, as_of=args.as_of)
    except ContractNotComparable as exc:
        return ToolOutcome(json.dumps({"error": exc.detail}))
    payload = comparison_to_json(comparison) | {"cite_as": RESULT_KEY}
    sources, citations = _element_sources(ctx, set(comparison.cited_element_ids))
    content = json.dumps(payload)
    return ToolOutcome(
        content,
        sources=sources | {RESULT_KEY: content},
        citations=citations | {RESULT_KEY: {"kind": "tool", "tool": "compare_contract_to_billing",
                                            "inputs_cited": sorted(citations)}},
        result_amount_minor=comparison.annual_gap_minor, result_currency=comparison.currency,
    )


def contract_tools() -> list[ToolSpec]:
    return [
        ToolSpec("get_contract_fields", "Validated fee terms of one contract, with the clause ids to cite.", FieldsArgs, _get_contract_fields),
        ToolSpec("compare_contract_to_billing",
                 "Compare a client contract's validated fee schedule with what billing charges; returns the annual gap. "
                 "Cite the result by its cite_as id.", CompareArgs, _compare),
    ]
