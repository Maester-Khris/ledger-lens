import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.main import include_routes

WRITES = {
    ("/documents", "POST"), ("/postings", "POST"), ("/postings/{posting_id}/reversal", "POST"),
    ("/fee-runs", "POST"), ("/gl-exports", "POST"),
}


def _mounted(demo_mode: bool) -> set[tuple[str, str]]:
    app = FastAPI()
    include_routes(app, demo_mode=demo_mode)
    return {(route.path, method) for route in app.routes for method in (getattr(route, "methods", None) or ())}


def test_public_writes_are_mounted_outside_demo_mode():
    assert WRITES <= _mounted(demo_mode=False)


def test_demo_mode_leaves_out_every_public_write_and_keeps_the_reads():
    mounted = _mounted(demo_mode=True)
    assert not WRITES & mounted
    assert {
        ("/documents", "GET"), ("/postings", "GET"), ("/fee-calculations/{calculation_id}", "GET"),
        ("/gl-exports/{export_id}.csv", "GET"), ("/reviews", "POST"), ("/tool-invocations/{invocation_id}/decision", "POST"),
    } <= mounted


def test_demo_mode_answers_405_or_404_for_the_writes():
    app = FastAPI()
    include_routes(app, demo_mode=True)
    client = TestClient(app)
    assert client.post("/documents").status_code == 405  # the path still serves GET
    assert client.post("/postings", json={}).status_code == 405
    assert client.post(f"/postings/{uuid.uuid4()}/reversal").status_code == 404
    assert client.post("/fee-runs", json={}).status_code == 404
    assert client.post("/gl-exports", json={}).status_code == 404


def test_config_reports_demo_mode(client, monkeypatch):
    assert client.get("/config").json()["demo_mode"] is False
    monkeypatch.setattr(config, "DEMO_MODE", True)
    assert client.get("/config").json()["demo_mode"] is True


