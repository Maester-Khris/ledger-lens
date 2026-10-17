"""N8 S8 Medium: the approval card shows the contract, the date and the clauses behind a proposed amount."""
import uuid

from app import config
from app.documents import dao as documents_dao
from app.documents.models import DocumentElement
from app.documents.redact import PiiSpan, apply_redaction
from app.documents.sniff import PdfFacts
from app.documents.types import ElementKind
from app.governance.dao import InvocationRecord, record_invocation
from app.ledger.dao import EntryInput
from app.ledger.types import Direction
from tests.test_contracts_compare import FIXTURE
from tests.test_governance import MODEL, accounts  # noqa: F401  (accounts is a fixture)


def _cited_contract(db_session, tenant_id) -> tuple[uuid.UUID, uuid.UUID]:
    data = FIXTURE.read_bytes()
    version = documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="tremblay-ima", title="Tremblay IMA", source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version
    redaction = apply_redaction("Marie Tremblay pays 0.85% on the next $1,500,000", [PiiSpan(0, 14, "PERSON", 0.9)],
                                tenant_id, config.PII_HMAC_KEY)
    element = DocumentElement(version_id=version.id, ordinal=0, kind=ElementKind.paragraph, section_path=["4. Fees"],
                              page_start=2, page_end=2, text_redacted=redaction.text, parser_version="t")
    db_session.add(element)
    documents_dao.save_tokens(db_session, tenant_id, redaction.tokens, config.PII_VAULT_KEY)
    db_session.flush()
    return version.document_id, element.id


def _record(db_session, tenant_id, tool, document_id, element_id, entries=None):
    return record_invocation(db_session, InvocationRecord(
        tenant_id=tenant_id, session_id="s", tool_name=tool, tool_version="1.0.0", model=MODEL,
        input={"document_id": str(document_id), "as_of": "2026-09-30"}, result_amount_minor=40_000,
        result_currency="CAD", citation={"ids": [str(element_id)]}, proposed_entries=entries,
    ))


def test_a_proposal_lists_its_contract_and_each_cited_clause_with_its_page(client, db_session, tenant_id, accounts):
    receivable, income = accounts
    document_id, element_id = _cited_contract(db_session, tenant_id)
    _record(db_session, tenant_id, "compare_contract_to_billing", document_id, element_id,
            (EntryInput(receivable.id, Direction.debit, 40_000), EntryInput(income.id, Direction.credit, 40_000)))
    _record(db_session, tenant_id, "get_contract_fields", document_id, element_id)  # no proposal: nothing resolved
    db_session.commit()

    by_tool = {i["tool_name"]: i for i in client.get("/tool-invocations").json()}
    proposal = by_tool["compare_contract_to_billing"]
    assert proposal["document_title"] == "Tremblay IMA" and proposal["document_version"] == 1
    assert proposal["sources"] == [{"element_id": str(element_id), "page": 2, "section": "4. Fees",
                                    "quote": "Marie Tremblay pays 0.85% on the next $1,500,000"}]  # revealed for display
    assert by_tool["get_contract_fields"]["sources"] == [] and by_tool["get_contract_fields"]["document_title"] is None
