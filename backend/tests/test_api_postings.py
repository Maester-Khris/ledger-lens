import uuid

import pytest

from app.ledger.dao import EntryInput, PostingRequest, create_account, create_posting
from app.ledger.types import Direction, NormalBalance

PROBLEM = "application/problem+json"


@pytest.fixture()
def pair(db_session, tenant_id):
    cash = create_account(db_session, tenant_id=tenant_id, name="Cash", currency="CAD", normal_balance=NormalBalance.debit)
    revenue = create_account(
        db_session, tenant_id=tenant_id, name="Revenue", currency="CAD", normal_balance=NormalBalance.credit
    )
    return cash, revenue


def _body(pair, amount=1000, **extra):
    cash, revenue = pair
    body = {
        "description": "Sale",
        "entries": [
            {"account_id": str(cash.id), "direction": "debit", "amount": amount},
            {"account_id": str(revenue.id), "direction": "credit", "amount": amount},
        ],
    }
    body.update(extra)
    return body


def _post(client, body, key=None):
    headers = {} if key is None else {"Idempotency-Key": key}
    return client.post("/postings", json=body, headers=headers)


def test_create_posting_returns_201_with_entries(client, pair):
    response = _post(client, _body(pair), key=str(uuid.uuid4()))
    assert response.status_code == 201
    assert "Idempotent-Replayed" not in response.headers
    payload = response.json()
    assert payload["source"] == "api"
    assert sorted(e["amount"] for e in payload["entries"]) == [1000, 1000]
    assert payload["reversed_by_posting_id"] is None


def test_retry_with_same_key_and_body_replays_with_200(client, pair):
    key = str(uuid.uuid4())
    first = _post(client, _body(pair), key=key)
    second = _post(client, _body(pair), key=key)
    assert second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert second.json()["id"] == first.json()["id"]


def test_reused_key_with_different_body_is_422_problem(client, pair):
    key = str(uuid.uuid4())
    _post(client, _body(pair, amount=1000), key=key)
    response = _post(client, _body(pair, amount=5), key=key)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    assert response.json()["type"] == "/problems/idempotency-key-reused"


@pytest.mark.parametrize("key", [None, "", "   ", "k" * 256])
def test_missing_or_invalid_idempotency_key_is_400(client, pair, key):
    response = _post(client, _body(pair), key=key)
    assert response.status_code == 400
    assert response.json()["type"] in {"/problems/idempotency-key-missing", "/problems/idempotency-key-invalid"}


def test_unbalanced_posting_is_422_posting_invalid(client, pair):
    body = _body(pair)
    body["entries"][1]["amount"] = 999
    response = _post(client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["type"] == "/problems/posting-invalid"
    assert any("balance per currency" in reason for reason in response.json()["reasons"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body["entries"][0].update(amount=10.5),
        lambda body: body["entries"][0].update(amount="1000"),
        lambda body: body.update(effective_at="2026-09-30T00:00:00"),  # no timezone
        lambda body: body.update(unexpected="field"),
        lambda body: body.update(source="fee_run"),  # clients cannot claim internal sources
    ],
)
def test_malformed_requests_are_422_request_invalid(client, pair, mutate):
    body = _body(pair)
    mutate(body)
    response = _post(client, body, key=str(uuid.uuid4()))
    assert response.status_code == 422
    assert response.json()["type"] == "/problems/request-invalid"


def test_concurrent_duplicate_is_409_with_retry_after(client, pair, session_factory, tenant_id):
    key = str(uuid.uuid4())
    cash, revenue = pair
    holder = session_factory()
    try:
        create_posting(
            holder,
            PostingRequest(
                tenant_id=tenant_id,
                idempotency_key=key,
                description="Sale",
                entries=(EntryInput(cash.id, Direction.debit, 1000), EntryInput(revenue.id, Direction.credit, 1000)),
            ),
        )
        response = _post(client, _body(pair), key=key)
    finally:
        holder.rollback()
        holder.close()
    assert response.status_code == 409
    assert response.headers["Retry-After"] == "1"
    assert response.json()["type"] == "/problems/request-in-progress"


def test_reversal_endpoint_creates_links_and_replays(client, pair):
    original = _post(client, _body(pair), key=str(uuid.uuid4())).json()
    first = client.post(f"/postings/{original['id']}/reversal")
    second = client.post(f"/postings/{original['id']}/reversal")
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["reverses_posting_id"] == original["id"]
    fetched = client.get(f"/postings/{original['id']}").json()
    assert fetched["reversed_by_posting_id"] == first.json()["id"]


def test_reversal_of_unknown_posting_is_404(client):
    response = client.post(f"/postings/{uuid.uuid4()}/reversal")
    assert response.status_code == 404
    assert response.json()["type"] == "/problems/posting-not-found"


def test_list_hides_stress_postings_and_pages_with_cursor(client, pair):
    ids = {_post(client, _body(pair), key=str(uuid.uuid4())).json()["id"] for _ in range(3)}
    _post(client, _body(pair, source="stress_test"), key=str(uuid.uuid4()))

    first = client.get("/postings", params={"limit": 2}).json()
    second = client.get("/postings", params={"limit": 2, "cursor": first["next_cursor"]}).json()

    seen = [p["id"] for p in first["items"]] + [p["id"] for p in second["items"]]
    assert set(seen) == ids and len(seen) == 3
    assert second["next_cursor"] is None


def test_invalid_cursor_is_400(client):
    response = client.get("/postings", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert response.json()["type"] == "/problems/cursor-invalid"


def test_get_unknown_posting_is_404(client):
    assert client.get(f"/postings/{uuid.uuid4()}").status_code == 404
