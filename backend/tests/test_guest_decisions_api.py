import uuid

import pytest

from app import config
from app.assistant.contract_tools import contract_tools
from app.assistant.tools import ToolContext, execute
from app.governance.dao import ModelConfig
from app.governance.models import ToolInvocation
from app.reporting import dashboard
from app.retrieval.vector_index import InMemoryVectorIndex
from sqlalchemy import select
from tests.fakes import RecordingEmbeddings
from tests.support import build_fee_scenario
from tests.test_contracts_compare import _contract
from tests.test_governance import accounts  # noqa: F401  (accounts is a fixture)
from tests.test_guest_decisions import _propose

TOOLS = {spec.name: spec for spec in contract_tools()}


@pytest.fixture()
def demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    dashboard._cache.clear()
    yield
    dashboard._cache.clear()


def _guest(client) -> dict[str, str]:
    return {"X-Guest-Id": client.post("/guests").json()["id"]}


def _compare_as(db_session, tenant_id, document_id, guest):
    ctx = ToolContext(session=db_session, tenant_id=tenant_id, session_id="s", turn_id=uuid.uuid4(),
                      embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                      model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY,
                      vault_key=config.PII_VAULT_KEY, overlay_guest=guest)
    return execute(TOOLS["compare_contract_to_billing"], ctx, {"document_id": str(document_id), "as_of": "2026-09-30"})


def test_the_tool_runner_records_the_guest_only_in_demo_mode(db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    guest = uuid.uuid4()
    _compare_as(db_session, tenant_id, document_id, guest)
    _compare_as(db_session, tenant_id, document_id, None)
    inputs = [i.input for i in db_session.scalars(select(ToolInvocation).where(ToolInvocation.tenant_id == tenant_id))]
    assert sorted(i.get("guest_id", "") for i in inputs) == ["", str(guest)]  # one per call, in either order


def test_a_demo_approval_is_not_recorded_and_stays_with_the_guest(demo, client, db_session, tenant_id, accounts):
    a, b = _guest(client), _guest(client)
    invocation = _propose(db_session, tenant_id, accounts, uuid.UUID(a["X-Guest-Id"]))
    assert client.get("/stats", headers=a).json()["approvals_pending"] == 1
    assert client.get("/stats", headers=b).json()["approvals_pending"] == 0

    response = client.post(f"/tool-invocations/{invocation.id}/decision", headers=a, json={"decision": "approved"})
    assert response.status_code == 201
    body = response.json()
    assert (body["recorded"], body["posting_id"], body["decided_by"]) == (False, None, "you (demo)")
    assert [i["decision"]["recorded"] for i in client.get("/tool-invocations", headers=a).json()] == [False]
    assert client.get("/tool-invocations", headers=b).json() == []
    assert client.post(f"/tool-invocations/{invocation.id}/decision", headers=b, json={"decision": "approved"}).status_code == 404
    assert client.get("/stats", headers=a).json()["approvals_pending"] == 0


def test_the_guests_timeline_shows_an_unrecorded_approval_and_no_posting(demo, client, db_session, tenant_id):
    scenario = build_fee_scenario(db_session, tenant_id)
    document_id = _contract(db_session, tenant_id, scenario.household_id)
    a = _guest(client)
    _compare_as(db_session, tenant_id, document_id, uuid.UUID(a["X-Guest-Id"]))
    invocation_id = db_session.scalars(select(ToolInvocation.id).where(ToolInvocation.tenant_id == tenant_id)).one()
    assert client.post(f"/tool-invocations/{invocation_id}/decision", headers=a, json={"decision": "approved"}).status_code == 201
    items = client.get(f"/documents/{document_id}/timeline", headers=a).json()
    decided = next(i for i in items if i["kind"] == "decided")
    assert decided["detail"]["recorded"] is False and decided["title"] == "approved by you (demo)"
    assert "posted" not in [i["kind"] for i in items]


def test_outside_demo_mode_an_approval_is_recorded(client, db_session, tenant_id, accounts):
    invocation = _propose(db_session, tenant_id, accounts, uuid.uuid4())
    body = client.post(f"/tool-invocations/{invocation.id}/decision", json={"decision": "approved"}).json()
    assert body["recorded"] is True and body["posting_id"] is not None
