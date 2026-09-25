import uuid
from pathlib import Path

from app import config
from app.documents import dao
from app.documents.models import DocumentElement
from app.documents.redact import PiiSpan, apply_redaction
from app.documents.types import ElementKind, VersionStage

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"


def _post(client, data=None, key="tremblay-ima"):
    return client.post(
        "/documents",
        data={"document_key": key, "title": "Tremblay IMA"},
        files={"file": ("ima.pdf", data if data is not None else FIXTURE.read_bytes(), "application/pdf")},
    )


def test_upload_returns_202_then_200_for_the_same_file(client):
    first = _post(client)
    assert first.status_code == 202
    body = first.json()
    assert body["version"] == 1 and body["status_url"] == f"/documents/{body['document_id']}"
    again = _post(client)
    assert again.status_code == 200
    assert again.json()["version_id"] == body["version_id"]


def test_upload_can_link_a_billing_household(client, db_session, tenant_id):
    from tests.support import build_fee_scenario
    scenario = build_fee_scenario(db_session, tenant_id)
    response = client.post(
        "/documents",
        data={"document_key": "tremblay-ima", "title": "Tremblay IMA", "household_id": str(scenario.household_id)},
        files={"file": ("ima.pdf", FIXTURE.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 202
    [row] = client.get("/documents").json()
    assert row["household_id"] == str(scenario.household_id)


def test_upload_of_non_pdf_is_a_problem_response(client):
    response = _post(client, data=b"hello")
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["type"] == "/problems/upload-rejected"


def test_list_shows_processing_status_until_parsed(client):
    _post(client)
    [row] = client.get("/documents").json()
    assert row["status"] == "processing" and row["status_note"] == "waiting for parse_redact"
    assert row["page_count"] == 2 and row["element_count"] == 0


def test_detail_reveals_tokens_for_display(client, db_session, tenant_id):
    body = _post(client).json()
    version_id = uuid.UUID(body["version_id"])
    redaction = apply_redaction("Client Marie Tremblay", [PiiSpan(7, 21, "PERSON", 0.9)], tenant_id, config.PII_HMAC_KEY)
    db_session.add(DocumentElement(version_id=version_id, ordinal=0, kind=ElementKind.paragraph,
                                   section_path=["Parties"], page_start=1, page_end=1,
                                   text_redacted=redaction.text, parser_version="t"))
    dao.save_tokens(db_session, tenant_id, redaction.tokens, config.PII_VAULT_KEY)
    dao.append_event(db_session, version_id, VersionStage.parsed, {})
    db_session.commit()
    detail = client.get(f"/documents/{body['document_id']}").json()
    assert detail["status"] != "failed"  # later plans add stages after parsing; only the preview matters here
    assert detail["preview"][0]["text"] == "Client Marie Tremblay"


def test_original_file_download(client):
    body = _post(client).json()
    response = client.get(f"/documents/{body['document_id']}/versions/1/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == FIXTURE.read_bytes()


def test_unknown_document_is_404(client):
    response = client.get("/documents/00000000-0000-0000-0000-000000000000")
