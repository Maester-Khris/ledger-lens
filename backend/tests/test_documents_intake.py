import uuid
from pathlib import Path

from app import config
from app.documents import dao, store
from app.documents.sniff import PdfFacts
from app.documents.types import VersionStage

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"


def _upload(db_session, tenant_id, *, key="tremblay-ima", data=None):
    data = data if data is not None else FIXTURE.read_bytes()
    return dao.register_upload(
        db_session, tenant_id=tenant_id, document_key=key, title="Tremblay IMA", source_url=None,
        data=data, facts=PdfFacts(page_count=2, byte_size=len(data)), uploaded_by="test",
        store_root=config.DOCUMENT_STORE_DIR,
    )


def test_first_upload_creates_version_one_with_a_stored_event(db_session, tenant_id):
    result = _upload(db_session, tenant_id)
    assert result.created is True
    assert result.version.version == 1
    assert store.original_path(config.DOCUMENT_STORE_DIR, result.version.file_sha256).read_bytes() == FIXTURE.read_bytes()
    assert [e.stage for e in dao.version_events(db_session, result.version.id)] == [VersionStage.stored]


def test_same_file_twice_is_a_noop(db_session, tenant_id):
    first = _upload(db_session, tenant_id)
    second = _upload(db_session, tenant_id)
    assert second.created is False
    assert second.version.id == first.version.id
    assert len(dao.version_events(db_session, first.version.id)) == 1


def test_new_file_for_same_document_is_the_next_version(db_session, tenant_id):
    _upload(db_session, tenant_id)
    changed = FIXTURE.read_bytes() + b"\n% amended\n"
    result = _upload(db_session, tenant_id, data=changed)
    assert result.created is True
    assert result.version.version == 2


def test_identical_bytes_under_two_documents(db_session, tenant_id):
    a = _upload(db_session, tenant_id, key="doc-a")
    b = _upload(db_session, tenant_id, key="doc-b")
    assert a.document.id != b.document.id
    assert a.version.id != b.version.id
    assert a.version.file_sha256 == b.version.file_sha256  # one file on disk, two version rows


def test_save_original_is_idempotent(tmp_path):
    first = store.save_original(tmp_path, b"%PDF-abc")
    second = store.save_original(tmp_path, b"%PDF-abc")
    assert first == second
    assert len(list(tmp_path.rglob("*"))) == 3  # originals/, originals/<2 hex>/, the file
