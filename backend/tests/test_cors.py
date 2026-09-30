import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import parse_frontend_origins
from app.main import install_cors

ALLOWED = "https://ledgerlens.nknext.dev"
REQUEST_HEADERS = "content-type,x-guest-id,idempotency-key,range"


def make_client(origins: list[str]) -> TestClient:
    app = FastAPI()

    @app.get("/x")
    def x() -> dict[str, bool]:
        return {"ok": True}

    install_cors(app, origins)
    return TestClient(app)


def test_preflight_from_the_frontend_origin_allows_every_header_the_frontend_sends():
    response = make_client([ALLOWED]).options(
        "/x",
        headers={"Origin": ALLOWED, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": REQUEST_HEADERS},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    allowed = response.headers["access-control-allow-headers"].lower()
    for header in REQUEST_HEADERS.split(","):
        assert header in allowed


def test_preflight_from_another_origin_is_refused_without_an_allow_origin_header():
    response = make_client([ALLOWED]).options(
        "/x", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_simple_request_from_the_frontend_origin_gets_the_origin_and_exposed_headers():
    response = make_client([ALLOWED]).get("/x", headers={"Origin": ALLOWED})
    assert response.headers["access-control-allow-origin"] == ALLOWED
    exposed = response.headers["access-control-expose-headers"].lower()
    for header in ("accept-ranges", "content-range", "content-length"):
        assert header in exposed


def test_no_origins_installs_no_middleware():
    response = make_client([]).get("/x", headers={"Origin": ALLOWED})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_parse_splits_on_commas_and_strips_spaces_and_trailing_slashes():
    assert parse_frontend_origins(" https://a.dev/ , http://localhost:5173 ") == ["https://a.dev", "http://localhost:5173"]


@pytest.mark.parametrize("raw", [None, "", "  ", " , "])
def test_parse_returns_empty_when_unset_or_blank(raw):
    assert parse_frontend_origins(raw) == []


@pytest.mark.parametrize("raw", ["ledgerlens.nknext.dev", "https://a.dev,b.dev", "*"])
def test_parse_rejects_an_entry_without_a_scheme(raw):
    with pytest.raises(ValueError, match="scheme"):
        parse_frontend_origins(raw)
