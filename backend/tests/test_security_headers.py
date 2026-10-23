from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.main import install_security_headers


def make_client() -> TestClient:
    app = FastAPI()

    @app.get("/json")
    def json_route() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/stream")
    def stream_route() -> StreamingResponse:
        return StreamingResponse(iter(["event: answer\ndata: {}\n\n"]), media_type="text/event-stream")

    install_security_headers(app)
    return TestClient(app)


def test_json_responses_carry_nosniff_and_same_origin_corp():
    response = make_client().get("/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"


def test_errors_and_streams_carry_them_too():
    client = make_client()
    for response in (client.get("/missing"), client.get("/stream")):
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert client.get("/stream").text == "event: answer\ndata: {}\n\n"
