import json
import uuid

from sqlalchemy import select

from app import config
from app.assistant.contract_tools import contract_tools
from app.assistant.tools import ToolContext, execute
from app.governance.dao import ModelConfig
from app.governance.models import ToolInvocation
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings
from tests.support import build_fee_scenario
from tests.test_contracts_compare import _contract

TOOLS = {spec.name: spec for spec in contract_tools()}


def _ctx(db_session, tenant_id):
    return ToolContext(session=db_session, tenant_id=tenant_id, session_id="s", turn_id=uuid.uuid4(),
                       embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                       model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY)


def test_compare_tool_is_citable_and_logs_the_amount(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    outcome = execute(TOOLS["compare_contract_to_billing"], _ctx(db_session, tenant_id),
                      {"document_id": str(document_id), "as_of": "2026-09-30"})
    invocation = db_session.scalars(select(ToolInvocation).where(ToolInvocation.tenant_id == tenant_id)).one()
    assert set(outcome.sources) == {str(invocation.id)}  # "@result" re-keyed to the invocation id
    assert "400.00" in outcome.sources[str(invocation.id)]
    assert (invocation.result_amount_minor, invocation.result_currency) == (40_000, "CAD")
    assert outcome.citations[str(invocation.id)]["kind"] == "tool"


def test_compare_tool_refusal_is_content_not_a_crash(db_session, tenant_id):
    document_id = _contract(db_session, tenant_id, None, key="edgar-fund")
    outcome = execute(TOOLS["compare_contract_to_billing"], _ctx(db_session, tenant_id), {"document_id": str(document_id)})
    assert "not linked to a billing household" in json.loads(outcome.content)["error"]
    assert outcome.sources == {}


def test_fields_tool_serves_only_validated_fields(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    outcome = execute(TOOLS["get_contract_fields"], _ctx(db_session, tenant_id), {"document_id": str(document_id)})
    body = json.loads(outcome.content)
    assert body["fields"]["currency"] == "CAD"
    assert body["fields"]["fee_tiers[1]"]["rate_text"] == "0.85%"
    assert body["not_validated"] == []


def test_positive_gap_is_proposed_for_approval_and_posts_once(db_session, tenant_id):
    from app.governance.dao import decide
    from app.governance.types import ToolDecision
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    execute(TOOLS["compare_contract_to_billing"], _ctx(db_session, tenant_id), {"document_id": str(document_id)})
    invocation = db_session.scalars(select(ToolInvocation).where(ToolInvocation.tenant_id == tenant_id)).one()
    assert invocation.approval_required is True
    decision = decide(db_session, tenant_id=tenant_id, invocation_id=invocation.id, decision=ToolDecision.approved,
                      decided_by="test", reason="contract says 0.85%")
    assert decision.posting_id is not None
