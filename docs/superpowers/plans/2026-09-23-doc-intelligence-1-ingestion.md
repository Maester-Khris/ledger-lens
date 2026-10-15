# Document Intelligence — Plan 1: Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept contract PDFs, store them content-addressed, parse them locally with Docling, tokenise PII with Presidio before anything is persisted as text, and run the stages in a separate worker process driven by an append-only event log.

**Architecture:** A new `app/documents` package (models, DAO, pure `sniff`/`markdown` helpers, `parse`, `redact`, `vault`, `store`). An app-level `app/ingestion_pipeline.py` sequences stages from the event log (plans 2 and 3 append their stages to it). `scripts/ingestion_worker.py` is the only process that loads Docling and spaCy. Routes stay thin.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Postgres 18, pypdf, Docling, Presidio analyzer (+ spaCy `en_core_web_lg`), cryptography (Fernet), pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-document-intelligence-design.md` (§3, §4.1, §5, §8, §9, §10)

## Global Constraints

- Record tables are append-only: every new record table gets the existing `forbid_mutation()` triggers for UPDATE/DELETE (row) and TRUNCATE (statement).
- The app role `ledger_app` has SELECT/INSERT only on the new tables (default privileges from migration `0003` already grant exactly that).
- No raw PII is ever written to Postgres as text. Only `text_redacted` and Fernet-encrypted vault values.
- Intake is **PDF only**, `MAX_UPLOAD_BYTES = 20 * 1024 * 1024`; encrypted or image-only PDFs → 422 problem+json, nothing stored.
- Routes stay thin (parse → call package function → return). No direct DB access outside `app/documents/dao.py`.
- Type hints on every function signature; dataclasses for DTOs.
- Pin exact versions in `backend/requirements.txt`.
- Tests run as the restricted app role; never clean up rows (fresh tenant per test).
- Commit style: conventional commits; stage files explicitly; **no AI co-author lines**.
- Run all commands from `backend/` unless stated otherwise.

## Review Focus

- **Same file uploaded twice for the same document** → 200 with the existing version, no new row, no new event. (Task 3 test `test_same_file_twice_is_a_noop`.)
- **Two different documents that happen to have identical bytes** → each gets its own version row; the store keeps one file. (Task 3 test `test_identical_bytes_under_two_documents`.)
- **A stage that raises** → a `failed` event with the stage name and error type; after `MAX_STAGE_ATTEMPTS` the version shows `failed` and the worker stops retrying it. (Task 7 tests.)
- **A PII value that appears twice, or in two documents** → the same token both times (deterministic), and one vault row. (Task 4 test `test_same_value_same_token_across_calls`.)
- **Overlapping Presidio detections** (e.g. a phone number inside a longer match) → exactly one replacement, never corrupted text. (Task 4 test `test_overlapping_spans_keep_the_longest`.)

---

## File structure

| File | Responsibility |
|---|---|
| `app/documents/__init__.py` | package marker |
| `app/documents/types.py` | `VersionStage`, `ElementKind`, `DocumentType` enums (pure) |
| `app/documents/errors.py` | `UploadRejected`, `DocumentNotFound`, `VersionNotFound` |
| `app/documents/sniff.py` | `inspect_pdf(bytes) -> PdfFacts` (pure, pypdf only) |
| `app/documents/store.py` | content-addressed file store |
| `app/documents/models.py` | ORM models for the five tables |
| `app/documents/dao.py` | all SQL for the package |
| `app/documents/markdown.py` | `render_markdown(elements)` (pure) |
| `app/documents/redact.py` | tokens, span merging, `PiiDetector` (Presidio) |
| `app/documents/vault.py` | Fernet encrypt/decrypt (the vault table itself is read/written in `dao.py`) |
| `app/documents/parse.py` | Docling → `ParsedDocument` |
| `app/documents/ingest.py` | `parse_and_redact` stage runner |
| `app/ingestion_pipeline.py` | stage specs, `next_stage`, `version_status`, `run_pending` |
| `app/routes/documents.py` | 4 endpoints |
| `alembic/versions/0008_documents.py` | schema |
| `scripts/ingestion_worker.py` | worker loop |
| `scripts/prepare_samples.py` | EDGAR → PDF samples + optional upload |
| `tests/fixtures/documents/*.html|*.pdf` | synthetic client agreement, blank "scan" |
| `tests/test_documents_*.py`, `tests/test_ingestion_pipeline.py` | tests |

---

### Task 1: PDF sniffing, dependencies, config and fixtures

**Files:**
- Modify: `backend/requirements.txt`, `backend/pytest.ini`, `backend/app/config.py`, `backend/.env.example`, `.gitignore` (repo root)
- Create: `backend/app/documents/__init__.py`, `backend/app/documents/types.py`, `backend/app/documents/errors.py`, `backend/app/documents/sniff.py`
- Create: `backend/tests/fixtures/documents/client_agreement.html`, `client_agreement.pdf`, `blank_scan.html`, `blank_scan.pdf`
- Test: `backend/tests/test_documents_sniff.py`

**Interfaces:**
- Produces: `inspect_pdf(data: bytes) -> PdfFacts(page_count: int, byte_size: int)`; `MAX_UPLOAD_BYTES`; `UploadRejected(DomainError)` (422, `upload-rejected`); `VersionStage`, `ElementKind`, `DocumentType` enums; `config.DOCUMENT_STORE_DIR: Path`, `config.PII_HMAC_KEY: str | None`, `config.PII_VAULT_KEY: str | None`, `config.require(name: str) -> str`; fixture paths `tests/fixtures/documents/client_agreement.pdf` (2 pages, contains PII) and `blank_scan.pdf` (no text).

- [ ] **Step 1: Add dependencies and install**

Append to `backend/requirements.txt`:
```
python-multipart==0.0.32
pypdf==6.19.0
docling==2.130.0
presidio-analyzer==2.2.364
cryptography==50.0.1
```
Run:
```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/docling-tools models download
.venv/bin/python -m spacy download en_core_web_lg
```
Expected: installs cleanly; model downloads finish. (`presidio-anonymizer` from the spec is intentionally **not** added: we replace spans ourselves with HMAC tokens in ~15 lines, see Task 4. Note this deviation in the PR summary.)

- [ ] **Step 2: Config, env example, gitignore, pytest markers**

Append to `backend/app/config.py`:
```python
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Original PDFs, content-addressed. Holds raw PII: never commit, back up like the database.
DOCUMENT_STORE_DIR = Path(os.environ.get("DOCUMENT_STORE_DIR", str(BACKEND_DIR / "var" / "documents")))

# Secrets: no defaults on purpose. Required only by code paths that tokenise or reveal PII.
PII_HMAC_KEY = os.environ.get("PII_HMAC_KEY")
PII_VAULT_KEY = os.environ.get("PII_VAULT_KEY")  # a Fernet key: Fernet.generate_key().decode()


def require(name: str) -> str:
    value = globals().get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; see backend/.env.example")
    return value
```
Append to `backend/.env.example`:
```
DOCUMENT_STORE_DIR=var/documents
# generate: python -c "import secrets; print(secrets.token_hex(32))"
PII_HMAC_KEY=change-me
# generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
PII_VAULT_KEY=change-me
SEC_USER_AGENT=Your Name your.email@example.com
```
Append to repo-root `.gitignore`:
```
backend/var/
```
Replace `backend/pytest.ini` with:
```ini
[pytest]
markers =
    stress: end-to-end concurrency proof against a live uvicorn server (run with: pytest -m stress)
    slow: runs real Docling/Presidio models locally (deselect with: pytest -m "not slow")
    eval: golden-set evaluation against real OpenAI/Pinecone (run with: pytest -m eval)
addopts = -m "not stress and not eval"
```

- [ ] **Step 3: Enums and errors**

`backend/app/documents/__init__.py`: empty file.

`backend/app/documents/types.py`:
```python
import enum

# Pure types shared by models, DAO and pure logic. No SQLAlchemy or FastAPI imports here.


class DocumentType(str, enum.Enum):
    contract = "contract"


class VersionStage(str, enum.Enum):
    stored = "stored"
    parsed = "parsed"
    indexed = "indexed"
    extracted = "extracted"
    failed = "failed"


class ElementKind(str, enum.Enum):
    heading = "heading"
    paragraph = "paragraph"
    table = "table"
```

`backend/app/documents/errors.py`:
```python
from app.errors import DomainError


class UploadRejected(DomainError):
    status = 422
    type_slug = "upload-rejected"
    title = "The uploaded file was rejected"


class DocumentNotFound(DomainError):
    status = 404
    type_slug = "document-not-found"
    title = "Document not found"


class VersionNotFound(DomainError):
    status = 404
    type_slug = "version-not-found"
    title = "Document version not found"
```

- [ ] **Step 4: Create the fixtures**

`backend/tests/fixtures/documents/client_agreement.html` (synthetic; mirrors the seeded Tremblay household, with tier 2 at **0.85%** where billing has 0.80% — the leakage demo):
```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Investment Management Agreement</title>
<style>body{font-family:Georgia,serif;font-size:12pt;margin:2cm} h1{font-size:20pt} h2{font-size:14pt;margin-top:1.2em}
.page-break{page-break-before:always} table{border-collapse:collapse} td,th{border:1px solid #444;padding:4px 10px}</style></head>
<body>
<h1>Investment Management Agreement</h1>
<p>This Investment Management Agreement (the "Agreement") is made as of December 15, 2025 and is effective as of January 1, 2026, between Maple Ridge Wealth Advisors Inc. (the "Adviser") and Marie Tremblay and Luc Tremblay (together, the "Client").</p>
<h2>1. Client Information</h2>
<p>Primary client: Marie Tremblay, Social Insurance Number 130 692 544, residing at 1450 Rue Sherbrooke Ouest, Montreal, Quebec H3G 1K4. Email: marie.tremblay@example.com. Telephone: 514-555-0142.</p>
<h2>2. Services</h2>
<p>The Adviser shall manage the Client's accounts on a discretionary basis in accordance with the Client's investment policy statement, as updated from time to time.</p>
<h2>3. Fees</h2>
<p>The Client shall pay the Adviser an annual management fee calculated on the combined household market value of the Client's accounts, as set out in Schedule A. Fees are calculated on a graduated basis, billed quarterly in arrears, and are payable in Canadian dollars.</p>
<h2>4. Termination</h2>
<p>Either party may terminate this Agreement upon thirty (30) days' written notice to the other party.</p>
<h2>5. Governing Law</h2>
<p>This Agreement shall be governed by the laws of the Province of Ontario.</p>
<div class="page-break"></div>
<h2>Schedule A — Fee Schedule</h2>
<table><tr><th>Household market value</th><th>Annual rate</th></tr>
<tr><td>On the first $1,000,000</td><td>1.00%</td></tr>
<tr><td>On the next $1,500,000</td><td>0.85%</td></tr>
<tr><td>On assets in excess of $2,500,000</td><td>0.65%</td></tr></table>
<h2>Signatures</h2>
<p>Maple Ridge Wealth Advisors Inc., by Jean Gagnon, Chief Compliance Officer.</p>
<p>Client: Marie Tremblay. Client: Luc Tremblay.</p>
</body></html>
```
`backend/tests/fixtures/documents/blank_scan.html`:
```html
<!doctype html><html><body style="margin:0"><div style="width:100%;height:1000px;background:#bbb"></div></body></html>
```
Render both to PDF with headless Chrome (committed so tests never need Chrome):
```bash
cd tests/fixtures/documents
for f in client_agreement blank_scan; do
  google-chrome --headless=new --no-pdf-header-footer --print-to-pdf="$PWD/$f.pdf" "file://$PWD/$f.html"
done
cd ../../..
.venv/bin/python -c "from pypdf import PdfReader; print(len(PdfReader('tests/fixtures/documents/client_agreement.pdf').pages))"
```
Expected: `2`.

- [ ] **Step 5: Write the failing tests**

`backend/tests/test_documents_sniff.py`:
```python
import io
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.documents.errors import UploadRejected
from app.documents.sniff import MAX_UPLOAD_BYTES, inspect_pdf

FIXTURES = Path(__file__).parent / "fixtures" / "documents"


def _bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_text_pdf_is_accepted_with_page_count():
    data = _bytes("client_agreement.pdf")
    facts = inspect_pdf(data)
    assert facts.page_count == 2
    assert facts.byte_size == len(data)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "empty"),
        (b"PK\x03\x04 not a pdf", "Only PDF"),
        (b"%PDF-1.7 truncated garbage", "could not be read"),
        (b"%PDF-" + b"0" * MAX_UPLOAD_BYTES, "limit"),
    ],
)
def test_bad_bytes_are_rejected(data, reason):
    with pytest.raises(UploadRejected) as exc_info:
        inspect_pdf(data)
    assert reason in exc_info.value.detail


def test_image_only_pdf_is_rejected_as_scanned():
    with pytest.raises(UploadRejected) as exc_info:
        inspect_pdf(_bytes("blank_scan.pdf"))
    assert "text layer" in exc_info.value.detail


def test_encrypted_pdf_is_rejected():
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_bytes("client_agreement.pdf"))))
    writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)
    with pytest.raises(UploadRejected) as exc_info:
        inspect_pdf(out.getvalue())
    assert "Encrypted" in exc_info.value.detail
```

- [ ] **Step 6: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_documents_sniff.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.documents.sniff'`.

- [ ] **Step 7: Implement `sniff.py`**

`backend/app/documents/sniff.py`:
```python
import io
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.documents.errors import UploadRejected

PDF_MAGIC = b"%PDF-"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MIN_TEXT_CHARS_PER_PAGE = 20  # fewer extractable characters than this = an image-only page
MAX_IMAGE_ONLY_PAGE_SHARE = 0.5


@dataclass(frozen=True)
class PdfFacts:
    page_count: int
    byte_size: int


def inspect_pdf(data: bytes) -> PdfFacts:
    """Reject anything the pipeline can't cite from: non-PDF, oversized, unreadable, encrypted, scanned."""
    if not data:
        raise UploadRejected("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"The file is {len(data)} bytes; the limit is {MAX_UPLOAD_BYTES}.")
    if not data.startswith(PDF_MAGIC):
        raise UploadRejected("Only PDF files are accepted.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UploadRejected("Encrypted PDFs are not accepted.")
        pages = list(reader.pages)
        image_only = sum(1 for page in pages if len((page.extract_text() or "").strip()) < MIN_TEXT_CHARS_PER_PAGE)
    except PdfReadError as exc:
        raise UploadRejected("The PDF could not be read.") from exc
    if not pages:
        raise UploadRejected("The PDF has no pages.")
    if image_only / len(pages) > MAX_IMAGE_ONLY_PAGE_SHARE:
        raise UploadRejected("The PDF has no usable text layer; scanned documents are not supported yet.")
    return PdfFacts(page_count=len(pages), byte_size=len(data))
```

- [ ] **Step 8: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_documents_sniff.py -v`
Expected: 7 passed. (If the truncated-garbage case raises a different pypdf exception class on this version, widen the `except` to `(PdfReadError, ValueError)` and re-run — do not catch bare `Exception`.)

- [ ] **Step 9: Commit**

```bash
git add requirements.txt pytest.ini app/config.py .env.example ../.gitignore app/documents/__init__.py app/documents/types.py app/documents/errors.py app/documents/sniff.py tests/fixtures/documents tests/test_documents_sniff.py
git commit -m "feat(documents): add PDF intake checks, fixtures and config"
```

---

### Task 2: Migration 0008 and ORM models

**Files:**
- Create: `backend/alembic/versions/0008_documents.py`, `backend/app/documents/models.py`
- Test: `backend/tests/test_documents_schema.py`

**Interfaces:**
- Consumes: enums from Task 1; `Base` from `app.ledger.models`; `forbid_mutation()` SQL function (migration 0004).
- Produces: ORM classes `Document` (with nullable `household_id` → `households.id`), `DocumentVersion`, `VersionEvent` (int `id` identity, orders events), `DocumentElement`, `PiiToken` in `app.documents.models`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_documents_schema.py`:
```python
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.documents.models import Document, DocumentElement, DocumentVersion, VersionEvent
from app.documents.types import DocumentType, ElementKind, VersionStage

SHA = "a" * 64


def _version(db_session, tenant_id, *, sha=SHA, version=1, key=None):
    document = Document(
        tenant_id=tenant_id, document_key=key or f"doc-{uuid.uuid4().hex[:8]}",
        doc_type=DocumentType.contract, title="IMA",
    )
    db_session.add(document)
    db_session.flush()
    row = DocumentVersion(
        document_id=document.id, version=version, file_sha256=sha, mime_type="application/pdf",
        byte_size=10, page_count=2, uploaded_by="test",
    )
    db_session.add(row)
    db_session.commit()
    return document, row


def test_version_numbers_and_file_hashes_are_unique_per_document(db_session, tenant_id):
    document, _ = _version(db_session, tenant_id)
    db_session.add(DocumentVersion(document_id=document.id, version=1, file_sha256="b" * 64,
                                   mime_type="application/pdf", byte_size=1, page_count=1, uploaded_by="t"))
    with pytest.raises(IntegrityError) as same_version:
        db_session.commit()
    assert same_version.value.orig.sqlstate == "23505"
    db_session.rollback()
    db_session.add(DocumentVersion(document_id=document.id, version=2, file_sha256=SHA,
                                   mime_type="application/pdf", byte_size=1, page_count=1, uploaded_by="t"))
    with pytest.raises(IntegrityError) as same_file:
        db_session.commit()
    assert same_file.value.orig.sqlstate == "23505"


def test_element_pages_must_be_ordered(db_session, tenant_id):
    _, version = _version(db_session, tenant_id)
    db_session.add(DocumentElement(version_id=version.id, ordinal=0, kind=ElementKind.paragraph,
                                   section_path=[], page_start=3, page_end=2, text_redacted="x", parser_version="t"))
    with pytest.raises(IntegrityError) as exc_info:
        db_session.commit()
    assert exc_info.value.orig.sqlstate == "23514"


@pytest.mark.parametrize("table", ["documents", "document_versions", "version_events", "document_elements", "pii_tokens"])
def test_record_tables_are_append_only(db_session, owner_session, tenant_id, table):
    _, version = _version(db_session, tenant_id)
    db_session.add(VersionEvent(version_id=version.id, stage=VersionStage.stored, detail={}))
    db_session.commit()
    statement = text(f"DELETE FROM {table}")
    with pytest.raises(ProgrammingError):  # the app role has no DELETE privilege
        db_session.execute(statement)
    db_session.rollback()
    if table in {"document_elements", "pii_tokens"}:
        return  # empty tables: a row trigger has nothing to fire on; the privilege check above is the guard
    with pytest.raises(IntegrityError) as exc_info:  # even the owner is stopped by forbid_mutation()
        owner_session.execute(statement)
    assert exc_info.value.orig.sqlstate == "23001"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_documents_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.documents.models'`.

- [ ] **Step 3: Write the migration**

`backend/alembic/versions/0008_documents.py`:
```python
"""documents: contracts, versions, event log, redacted elements, PII vault

Revision ID: 0008_documents
Revises: 0007_reporting
"""
from alembic import op

revision = "0008_documents"
down_revision = "0007_reporting"
branch_labels = None
depends_on = None

RECORD_TABLES = ("documents", "document_versions", "version_events", "document_elements", "pii_tokens")


def _run(*statements: str) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    _run(
        "CREATE TYPE document_type AS ENUM ('contract')",
        "CREATE TYPE version_stage AS ENUM ('stored', 'parsed', 'indexed', 'extracted', 'failed')",
        "CREATE TYPE element_kind AS ENUM ('heading', 'paragraph', 'table')",
        "CREATE TABLE documents ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " document_key text NOT NULL CHECK (document_key ~ '^[a-z0-9][a-z0-9-]{1,63}$'),"
        " doc_type document_type NOT NULL,"
        " title text NOT NULL CHECK (length(title) BETWEEN 1 AND 300),"
        " source_url text NULL,"
        # The billing household an advisory agreement belongs to; lets tools resolve it without
        # the model ever seeing household names. NULL for fund-level (EDGAR) agreements.
        " household_id uuid NULL REFERENCES households(id),"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_documents_tenant_key UNIQUE (tenant_id, document_key))",
        "CREATE TABLE document_versions ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " document_id uuid NOT NULL REFERENCES documents(id),"
        " version integer NOT NULL CHECK (version >= 1),"
        " file_sha256 text NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),"
        " mime_type text NOT NULL,"
        " byte_size bigint NOT NULL CHECK (byte_size > 0),"
        " page_count integer NOT NULL CHECK (page_count > 0),"
        " uploaded_by text NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " CONSTRAINT uq_versions_document_version UNIQUE (document_id, version),"
        " CONSTRAINT uq_versions_document_file UNIQUE (document_id, file_sha256))",
        "CREATE TABLE version_events ("
        " id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,"
        " version_id uuid NOT NULL REFERENCES document_versions(id),"
        " stage version_stage NOT NULL,"
        " detail jsonb NOT NULL DEFAULT '{}'::jsonb,"
        " created_at timestamptz NOT NULL DEFAULT clock_timestamp())",
        "CREATE INDEX ix_version_events_version ON version_events (version_id, id)",
        "CREATE INDEX ix_documents_household ON documents (household_id) WHERE household_id IS NOT NULL",
        "CREATE TABLE document_elements ("
        " id uuid PRIMARY KEY DEFAULT gen_random_uuid(),"
        " version_id uuid NOT NULL REFERENCES document_versions(id),"
        " ordinal integer NOT NULL CHECK (ordinal >= 0),"
        " kind element_kind NOT NULL,"
        " section_path text[] NOT NULL,"
        " page_start integer NOT NULL CHECK (page_start >= 1),"
        " page_end integer NOT NULL,"
        " text_redacted text NOT NULL CHECK (length(text_redacted) > 0),"
        " parser_version text NOT NULL,"
        " CONSTRAINT uq_elements_version_ordinal UNIQUE (version_id, ordinal),"
        " CONSTRAINT ck_elements_pages CHECK (page_start <= page_end))",
        "CREATE TABLE pii_tokens ("
        " tenant_id uuid NOT NULL REFERENCES tenants(id),"
        " token text NOT NULL CHECK (token ~ '^<[A-Z_]+_[0-9a-f]{12}>$'),"
        " entity_type text NOT NULL,"
        " value_encrypted bytea NOT NULL,"
        " created_at timestamptz NOT NULL DEFAULT now(),"
        " PRIMARY KEY (tenant_id, token))",
    )
    for table in RECORD_TABLES:
        _run(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_mutation()",
            f"CREATE TRIGGER trg_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()",
        )


def downgrade() -> None:
    _run(
        "DROP TABLE pii_tokens",
        "DROP TABLE document_elements",
        "DROP TABLE version_events",
        "DROP TABLE document_versions",
        "DROP TABLE documents",
        "DROP TYPE element_kind",
        "DROP TYPE version_stage",
        "DROP TYPE document_type",
    )
```

- [ ] **Step 4: Write the models**

`backend/app/documents/models.py`:
```python
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Identity, Integer, LargeBinary, Text, TIMESTAMP, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.documents.types import DocumentType, ElementKind, VersionStage
from app.ledger.models import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


def _created_at() -> Mapped[datetime]:
    return mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class Document(Base):
    __tablename__ = "documents"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    document_key: Mapped[str] = mapped_column(Text, nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(SAEnum(DocumentType, name="document_type", native_enum=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    household_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=True)
    created_at: Mapped[datetime] = _created_at()


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class VersionEvent(Base):
    __tablename__ = "version_events"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    stage: Mapped[VersionStage] = mapped_column(SAEnum(VersionStage, name="version_stage", native_enum=True), nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, server_default=func.clock_timestamp())


class DocumentElement(Base):
    __tablename__ = "document_elements"
    __mapper_args__ = {"eager_defaults": True}
    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_versions.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[ElementKind] = mapped_column(SAEnum(ElementKind, name="element_kind", native_enum=True), nullable=False)
    section_path: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    parser_version: Mapped[str] = mapped_column(Text, nullable=False)


class PiiToken(Base):
    __tablename__ = "pii_tokens"
    __mapper_args__ = {"eager_defaults": True}
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True)
    token: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = _created_at()
```
Add `import app.documents.models  # noqa: F401` next to the other model imports in `backend/alembic/env.py` if that file imports model modules for metadata (check with `grep -n "models" alembic/env.py`; if it only runs raw SQL migrations, skip).

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_documents_schema.py tests/test_migrations.py -v`
Expected: all passed (the migration round-trip test now covers 0008 up/down).

- [ ] **Step 6: Commit**

```bash
git add alembic/versions/0008_documents.py app/documents/models.py tests/test_documents_schema.py
git commit -m "feat(documents): add append-only document, version, event, element and vault tables"
```

---

### Task 3: Content-addressed store and upload registration

**Files:**
- Create: `backend/app/documents/store.py`, `backend/app/documents/dao.py`
- Modify: `backend/tests/conftest.py` (session-scoped secrets + store dir)
- Test: `backend/tests/test_documents_intake.py`

**Interfaces:**
- Consumes: `PdfFacts`, models.
- Produces:
  - `store.save_original(root: Path, data: bytes) -> str` (sha256 hex), `store.original_path(root: Path, sha256: str) -> Path`
  - `dao.UploadResult(document: Document, version: DocumentVersion, created: bool)`
  - `dao.register_upload(session, *, tenant_id: UUID, document_key: str, title: str, source_url: str | None, data: bytes, facts: PdfFacts, uploaded_by: str, store_root: Path, household_id: UUID | None = None) -> UploadResult`
  - `dao.append_event(session, version_id: UUID, stage: VersionStage, detail: dict) -> None` (adds, does not commit)
  - `dao.version_events(session, version_id: UUID) -> list[VersionEvent]` (ordered by id)
  - `dao.get_version(session, version_id: UUID) -> DocumentVersion` (raises `VersionNotFound`)
  - `dao.all_version_ids(session) -> list[UUID]`

- [ ] **Step 1: Add session-wide test secrets**

Append to `backend/tests/conftest.py`:
```python
from cryptography.fernet import Fernet


@pytest.fixture(scope="session", autouse=True)
def document_settings(tmp_path_factory):
    """Per-run secrets and store dir: tests never touch real keys or backend/var."""
    config.PII_HMAC_KEY = "test-hmac-key-" + "0" * 32
    config.PII_VAULT_KEY = Fernet.generate_key().decode()
    config.DOCUMENT_STORE_DIR = tmp_path_factory.mktemp("document-store")
    return config.DOCUMENT_STORE_DIR
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_documents_intake.py`:
```python
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
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_documents_intake.py -v`
Expected: FAIL with `ImportError: cannot import name 'dao'`.

- [ ] **Step 4: Implement the store**

`backend/app/documents/store.py`:
```python
import hashlib
import os
from pathlib import Path


def original_path(root: Path, sha256: str) -> Path:
    return root / "originals" / sha256[:2] / sha256


def save_original(root: Path, data: bytes) -> str:
    """Write once by content hash. A leftover file from a failed upload is harmless: same bytes, same name."""
    sha256 = hashlib.sha256(data).hexdigest()
    path = original_path(root, sha256)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".partial")
        partial.write_bytes(data)
        os.replace(partial, path)  # atomic on the same filesystem
    return sha256
```

- [ ] **Step 5: Implement the DAO (intake part)**

`backend/app/documents/dao.py`:
```python
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.documents import store
from app.documents.errors import VersionNotFound
from app.documents.models import Document, DocumentVersion, VersionEvent
from app.documents.sniff import PdfFacts
from app.documents.types import DocumentType, VersionStage

PDF_MIME = "application/pdf"


@dataclass(frozen=True)
class UploadResult:
    document: Document
    version: DocumentVersion
    created: bool


def _document(
    session: Session, tenant_id: uuid.UUID, document_key: str, title: str, source_url: str | None,
    household_id: uuid.UUID | None,
) -> Document:
    session.execute(
        insert(Document)
        .values(tenant_id=tenant_id, document_key=document_key, doc_type=DocumentType.contract,
                title=title, source_url=source_url, household_id=household_id)
        .on_conflict_do_nothing(constraint="uq_documents_tenant_key")
    )
    return session.scalars(
        select(Document).where(Document.tenant_id == tenant_id, Document.document_key == document_key)
    ).one()


def register_upload(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    document_key: str,
    title: str,
    source_url: str | None,
    data: bytes,
    facts: PdfFacts,
    uploaded_by: str,
    store_root: Path,
    household_id: uuid.UUID | None = None,
) -> UploadResult:
    """The first upload of a document_key sets its title, source and household; later versions keep them."""
    sha256 = store.save_original(store_root, data)
    for attempt in range(2):  # one retry: a concurrent upload may take the next version number first
        document = _document(session, tenant_id, document_key, title, source_url, household_id)
        existing = session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id, DocumentVersion.file_sha256 == sha256)
        ).one_or_none()
        if existing is not None:
            session.commit()
            return UploadResult(document, existing, created=False)
        next_version = session.scalar(
            select(func.coalesce(func.max(DocumentVersion.version), 0) + 1).where(DocumentVersion.document_id == document.id)
        )
        version = DocumentVersion(
            document_id=document.id, version=next_version, file_sha256=sha256, mime_type=PDF_MIME,
            byte_size=facts.byte_size, page_count=facts.page_count, uploaded_by=uploaded_by,
        )
        try:
            session.add(version)
            session.flush()
            append_event(session, version.id, VersionStage.stored, {"file_sha256": sha256})
            session.commit()
            return UploadResult(document, version, created=True)
        except IntegrityError:
            session.rollback()
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


def append_event(session: Session, version_id: uuid.UUID, stage: VersionStage, detail: dict) -> None:
    session.add(VersionEvent(version_id=version_id, stage=stage, detail=detail))


def version_events(session: Session, version_id: uuid.UUID) -> list[VersionEvent]:
    return list(session.scalars(select(VersionEvent).where(VersionEvent.version_id == version_id).order_by(VersionEvent.id)))


def get_version(session: Session, version_id: uuid.UUID) -> DocumentVersion:
    version = session.get(DocumentVersion, version_id)
    if version is None:
        raise VersionNotFound(f"Document version {version_id} does not exist.")
    return version


def all_version_ids(session: Session) -> list[uuid.UUID]:
    # ponytail: scans every version on each worker poll; add a "pending" query when the corpus grows past hundreds
    return list(session.scalars(select(DocumentVersion.id).order_by(DocumentVersion.created_at)))
```

- [ ] **Step 6: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_documents_intake.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add app/documents/store.py app/documents/dao.py tests/conftest.py tests/test_documents_intake.py
git commit -m "feat(documents): register uploads with content-addressed storage and versioning"
```

---

### Task 4: PII tokens, redaction and the vault

**Files:**
- Create: `backend/app/documents/redact.py`, `backend/app/documents/vault.py`
- Modify: `backend/app/documents/dao.py`
- Test: `backend/tests/test_documents_redact.py`

**Interfaces:**
- Produces:
  - `redact.PII_ENTITIES: tuple[str, ...]`, `redact.TOKEN_PATTERN: re.Pattern`
  - `redact.PiiSpan(start: int, end: int, entity_type: str, score: float)`
  - `redact.Redaction(text: str, tokens: dict[str, tuple[str, str]])` — token → (entity_type, original value)
  - `redact.make_token(tenant_id: UUID, entity_type: str, value: str, key: str) -> str` → `"<PERSON_1a2b3c4d5e6f>"`
  - `redact.apply_redaction(text: str, spans: Sequence[PiiSpan], tenant_id: UUID, key: str) -> Redaction`
  - `redact.PiiDetector().detect(text: str) -> list[PiiSpan]` (loads Presidio once)
  - `vault.encrypt_value(value: str, key: str) -> bytes`, `vault.decrypt_value(blob: bytes, key: str) -> str`
  - `dao.save_tokens(session, tenant_id: UUID, tokens: Mapping[str, tuple[str, str]], key: str) -> None` (no commit, ON CONFLICT DO NOTHING)
  - `dao.reveal(session, tenant_id: UUID, texts: Sequence[str], key: str) -> list[str]`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_documents_redact.py`:
```python
import uuid

import pytest

from app import config
from app.documents import dao, vault
from app.documents.redact import PiiDetector, PiiSpan, TOKEN_PATTERN, apply_redaction, make_token

KEY = "k" * 32
TENANT = uuid.UUID("00000000-0000-0000-0000-00000000000a")


def test_same_value_same_token_across_calls():
    a = make_token(TENANT, "PERSON", "Marie  Tremblay", KEY)
    b = make_token(TENANT, "PERSON", "marie tremblay", KEY)  # whitespace and case normalised
    assert a == b
    assert TOKEN_PATTERN.fullmatch(a)


def test_token_depends_on_tenant_type_and_key():
    base = make_token(TENANT, "PERSON", "Marie Tremblay", KEY)
    assert make_token(uuid.uuid4(), "PERSON", "Marie Tremblay", KEY) != base
    assert make_token(TENANT, "EMAIL_ADDRESS", "Marie Tremblay", KEY) != base
    assert make_token(TENANT, "PERSON", "Marie Tremblay", "x" * 32) != base


def test_apply_redaction_replaces_spans_and_collects_values():
    text = "Client Marie Tremblay, SIN 130 692 544."
    spans = [PiiSpan(7, 21, "PERSON", 0.85), PiiSpan(27, 38, "CA_SIN", 1.0)]
    result = apply_redaction(text, spans, TENANT, KEY)
    assert "Marie" not in result.text and "130 692 544" not in result.text
    assert result.text.startswith("Client <PERSON_") and result.text.endswith(">.")
    assert sorted(v[1] for v in result.tokens.values()) == ["130 692 544", "Marie Tremblay"]


def test_overlapping_spans_keep_the_longest():
    text = "Call 514-555-0142 now"
    spans = [PiiSpan(5, 17, "PHONE_NUMBER", 0.7), PiiSpan(9, 17, "US_BANK_NUMBER", 0.4)]
    result = apply_redaction(text, spans, TENANT, KEY)
    assert result.text.count("<") == 1
    assert list(result.tokens.values()) == [("PHONE_NUMBER", "514-555-0142")]


def test_vault_round_trip():
    blob = vault.encrypt_value("130 692 544", config.PII_VAULT_KEY)
    assert b"130" not in blob
    assert vault.decrypt_value(blob, config.PII_VAULT_KEY) == "130 692 544"


def test_reveal_replaces_known_tokens(db_session, tenant_id):
    redaction = apply_redaction("Client Marie Tremblay", [PiiSpan(7, 21, "PERSON", 0.9)], tenant_id, config.PII_HMAC_KEY)
    dao.save_tokens(db_session, tenant_id, redaction.tokens, config.PII_VAULT_KEY)
    dao.save_tokens(db_session, tenant_id, redaction.tokens, config.PII_VAULT_KEY)  # second save is a no-op
    db_session.commit()
    assert dao.reveal(db_session, tenant_id, [redaction.text, "no tokens"], config.PII_VAULT_KEY) == [
        "Client Marie Tremblay", "no tokens",
    ]


@pytest.mark.slow
def test_presidio_finds_name_sin_email_and_phone():
    text = ("Primary client: Marie Tremblay, Social Insurance Number 130 692 544. "
            "Email: marie.tremblay@example.com. Telephone: 514-555-0142.")
    found = {span.entity_type for span in PiiDetector().detect(text)}
    assert {"PERSON", "CA_SIN", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= found


@pytest.mark.slow
def test_presidio_leaves_governing_law_and_dates_alone():
    text = "This Agreement shall be governed by the laws of the Province of Ontario, effective January 1, 2026."
    assert PiiDetector().detect(text) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_documents_redact.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.documents.redact'`.

- [ ] **Step 3: Implement `redact.py`**

`backend/app/documents/redact.py`:
```python
import hashlib
import hmac
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

# Personal data only. Organisations, locations and dates stay readable: contracts need
# "Province of Ontario" and "January 1, 2026" as terms. Known gap: a street address is not tokenised.
PII_ENTITIES = (
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CA_SIN", "US_SSN", "CREDIT_CARD", "IBAN_CODE", "US_BANK_NUMBER",
)
MIN_PII_SCORE = 0.5
TOKEN_DIGEST_CHARS = 12
TOKEN_PATTERN = re.compile(r"<([A-Z_]+)_([0-9a-f]{12})>")


@dataclass(frozen=True)
class PiiSpan:
    start: int
    end: int
    entity_type: str
    score: float


@dataclass(frozen=True)
class Redaction:
    text: str
    tokens: dict[str, tuple[str, str]] = field(default_factory=dict)  # token -> (entity_type, original value)


def _normalise(value: str) -> str:
    return " ".join(value.split()).casefold()


def make_token(tenant_id: uuid.UUID, entity_type: str, value: str, key: str) -> str:
    """Deterministic per tenant: the same person gets the same token in every document and in queries."""
    message = f"{tenant_id}|{entity_type}|{_normalise(value)}".encode()
    digest = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:TOKEN_DIGEST_CHARS]
    return f"<{entity_type}_{digest}>"


def _non_overlapping(spans: Sequence[PiiSpan]) -> list[PiiSpan]:
    kept: list[PiiSpan] = []
    for span in sorted(spans, key=lambda s: (-(s.end - s.start), -s.score, s.start)):
        if all(span.end <= k.start or span.start >= k.end for k in kept):
            kept.append(span)
    return sorted(kept, key=lambda s: s.start)


def apply_redaction(text: str, spans: Sequence[PiiSpan], tenant_id: uuid.UUID, key: str) -> Redaction:
    tokens: dict[str, tuple[str, str]] = {}
    pieces: list[str] = []
    cursor = 0
    for span in _non_overlapping(spans):
        value = text[span.start:span.end]
        token = make_token(tenant_id, span.entity_type, value, key)
        tokens[token] = (span.entity_type, value)
        pieces.append(text[cursor:span.start])
        pieces.append(token)
        cursor = span.end
    pieces.append(text[cursor:])
    return Redaction("".join(pieces), tokens)


class PiiDetector:
    """Presidio analyzer with the Canadian SIN recognizer switched on (it ships disabled)."""

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.predefined_recognizers import CaSinRecognizer

        self._engine = AnalyzerEngine()
        self._engine.registry.add_recognizer(CaSinRecognizer())

    def detect(self, text: str) -> list[PiiSpan]:
        results = self._engine.analyze(text=text, entities=list(PII_ENTITIES), language="en")
        return [PiiSpan(r.start, r.end, r.entity_type, r.score) for r in results if r.score >= MIN_PII_SCORE]
```
If `CaSinRecognizer` is not importable from `presidio_analyzer.predefined_recognizers` in 2.2.364, locate it with `grep -rn "class CaSinRecognizer" .venv/lib/python3.12/site-packages/presidio_analyzer` and import from that module.

- [ ] **Step 4: Implement `vault.py`**

`backend/app/documents/vault.py` (crypto only; the token table is read and written by `dao.py`, per the layering rule):
```python
from cryptography.fernet import Fernet


def encrypt_value(value: str, key: str) -> bytes:
    return Fernet(key.encode()).encrypt(value.encode())


def decrypt_value(blob: bytes, key: str) -> str:
    return Fernet(key.encode()).decrypt(blob).decode()
```
Append to `backend/app/documents/dao.py` (add `from collections.abc import Mapping, Sequence`, `from app.documents import vault`, `from app.documents.models import PiiToken`, `from app.documents.redact import TOKEN_PATTERN`):
```python
def save_tokens(session: Session, tenant_id: uuid.UUID, tokens: Mapping[str, tuple[str, str]], key: str) -> None:
    """No commit. A token already in the vault is left alone (same value, same token)."""
    if not tokens:
        return
    rows = [
        {"tenant_id": tenant_id, "token": token, "entity_type": entity_type, "value_encrypted": vault.encrypt_value(value, key)}
        for token, (entity_type, value) in tokens.items()
    ]
    session.execute(insert(PiiToken).values(rows).on_conflict_do_nothing(index_elements=["tenant_id", "token"]))


def reveal(session: Session, tenant_id: uuid.UUID, texts: Sequence[str], key: str) -> list[str]:
    """Display only: swap tokens back to values. Unknown tokens stay as they are."""
    wanted = {match.group(0) for text in texts for match in TOKEN_PATTERN.finditer(text)}
    if not wanted:
        return list(texts)
    values = {
        row.token: vault.decrypt_value(row.value_encrypted, key)
        for row in session.scalars(select(PiiToken).where(PiiToken.tenant_id == tenant_id, PiiToken.token.in_(wanted)))
    }
    return [TOKEN_PATTERN.sub(lambda m: values.get(m.group(0), m.group(0)), text) for text in texts]
```
- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_documents_redact.py -v`
Expected: 8 passed (the two `slow` tests load spaCy; ~10–20 s).
If `test_presidio_leaves_governing_law_and_dates_alone` fails because PERSON fires on a capitalised phrase, print the spans, and raise `MIN_PII_SCORE` only if the false positive scores below the true positives in the other test; otherwise keep 0.5 and adjust the test sentence — do not drop PERSON.

- [ ] **Step 6: Commit**

```bash
git add app/documents/redact.py app/documents/vault.py app/documents/dao.py tests/test_documents_redact.py
git commit -m "feat(documents): tokenise PII with deterministic HMAC tokens and an encrypted vault"
```

---

### Task 5: Docling parsing into elements

**Files:**
- Create: `backend/app/documents/parse.py`, `backend/app/documents/markdown.py`
- Test: `backend/tests/test_documents_parse.py`

**Interfaces:**
- Produces:
  - `parse.ParsedElement(kind: ElementKind, text: str, section_path: tuple[str, ...], page_start: int, page_end: int)`
  - `parse.ParsedDocument(elements: tuple[ParsedElement, ...], page_grades: dict[int, str], parser_version: str)` — grades are `"POOR" | "FAIR" | "GOOD" | "EXCELLENT"`, keys are 1-based page numbers
  - `parse.parse_pdf(path: Path) -> ParsedDocument`
  - `markdown.MarkdownElement(kind: ElementKind, section_path: Sequence[str], text: str)`; `markdown.render_markdown(elements: Sequence[MarkdownElement]) -> str`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_documents_parse.py`:
```python
from pathlib import Path

import pytest

from app.documents.markdown import MarkdownElement, render_markdown
from app.documents.parse import parse_pdf
from app.documents.types import ElementKind

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"


def test_render_markdown_uses_section_depth_for_headings():
    elements = [
        MarkdownElement(ElementKind.heading, ["Agreement"], "Agreement"),
        MarkdownElement(ElementKind.heading, ["Agreement", "3. Fees"], "3. Fees"),
        MarkdownElement(ElementKind.paragraph, ["Agreement", "3. Fees"], "Billed quarterly."),
        MarkdownElement(ElementKind.table, ["Agreement", "3. Fees"], "| a | b |\n|---|---|"),
    ]
    assert render_markdown(elements) == "# Agreement\n\n## 3. Fees\n\nBilled quarterly.\n\n| a | b |\n|---|---|\n"


@pytest.mark.slow
def test_docling_keeps_structure_and_pages():
    parsed = parse_pdf(FIXTURE)
    kinds = {e.kind for e in parsed.elements}
    assert {ElementKind.heading, ElementKind.paragraph, ElementKind.table} <= kinds
    fee_table = next(e for e in parsed.elements if e.kind is ElementKind.table)
    assert fee_table.page_start == 2
    assert "0.85%" in fee_table.text
    termination = next(e for e in parsed.elements if "thirty (30) days" in e.text)
    assert termination.page_start == 1
    assert any("Termination" in part for part in termination.section_path)
    assert set(parsed.page_grades) == {1, 2}
    assert all(grade in {"POOR", "FAIR", "GOOD", "EXCELLENT"} for grade in parsed.page_grades.values())
    assert parsed.parser_version.startswith("docling ")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_documents_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.documents.markdown'`.

- [ ] **Step 3: Implement `markdown.py`**

`backend/app/documents/markdown.py`:
```python
from collections.abc import Sequence
from dataclasses import dataclass

from app.documents.types import ElementKind

MAX_HEADING_DEPTH = 6


@dataclass(frozen=True)
class MarkdownElement:
    kind: ElementKind
    section_path: Sequence[str]
    text: str


def render_markdown(elements: Sequence[MarkdownElement]) -> str:
    """The markdown view is derived, never stored: document_elements are the record."""
    blocks = []
    for element in elements:
        if element.kind is ElementKind.heading:
            depth = min(max(len(element.section_path), 1), MAX_HEADING_DEPTH)
            blocks.append(f"{'#' * depth} {element.text}")
        else:
            blocks.append(element.text)
    return "\n\n".join(blocks) + "\n"
```

- [ ] **Step 4: Implement `parse.py`**

`backend/app/documents/parse.py`:
```python
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path

from app.documents.types import ElementKind

GRADES = ("POOR", "FAIR", "GOOD", "EXCELLENT")


@dataclass(frozen=True)
class ParsedElement:
    kind: ElementKind
    text: str
    section_path: tuple[str, ...]
    page_start: int
    page_end: int


@dataclass(frozen=True)
class ParsedDocument:
    elements: tuple[ParsedElement, ...]
    page_grades: dict[int, str]
    parser_version: str


@lru_cache(maxsize=1)
def _converter():
    from docling.document_converter import DocumentConverter

    return DocumentConverter()  # loads layout/table models once per process


def _grade(value: object) -> str:
    name = getattr(value, "name", str(value)).upper()
    return name if name in GRADES else "POOR"  # an unknown grade is treated as the worst case


def parse_pdf(path: Path) -> ParsedDocument:
    from docling_core.types.doc import DocItemLabel, TableItem

    heading_labels = {DocItemLabel.TITLE, DocItemLabel.SECTION_HEADER}
    text_labels = {DocItemLabel.TEXT, DocItemLabel.PARAGRAPH, DocItemLabel.LIST_ITEM, DocItemLabel.CAPTION}

    result = _converter().convert(str(path))
    document = result.document
    stack: list[tuple[int, str]] = []  # (heading level, heading text)
    elements: list[ParsedElement] = []
    for item, _depth in document.iterate_items():
        pages = [prov.page_no for prov in getattr(item, "prov", [])] or [1]
        if item.label in heading_labels:
            level = 0 if item.label is DocItemLabel.TITLE else getattr(item, "level", 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, item.text.strip()))
            kind, text = ElementKind.heading, item.text.strip()
        elif isinstance(item, TableItem):
            kind, text = ElementKind.table, item.export_to_markdown(doc=document).strip()
        elif item.label in text_labels:
            kind, text = ElementKind.paragraph, item.text.strip()
        else:
            continue  # page headers/footers, pictures: not citable content
        if text:
            elements.append(ParsedElement(kind, text, tuple(t for _, t in stack), min(pages), max(pages)))

    page_grades = {
        int(index) + 1: _grade(scores.mean_grade)  # Docling keys pages by 0-based index
        for index, scores in result.confidence.pages.items()
    }
    return ParsedDocument(tuple(elements), page_grades, f"docling {version('docling')}")
```
If the slow test fails on the confidence keys (e.g. they are already 1-based on this version), print `result.confidence.pages.keys()` for the 2-page fixture and drop the `+ 1` if keys are `{1, 2}`. If `iterate_items` yields a `SectionHeaderItem` for the title, the stack logic still holds.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_documents_parse.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add app/documents/parse.py app/documents/markdown.py tests/test_documents_parse.py
git commit -m "feat(documents): parse PDFs locally with Docling into cited elements"
```

---

### Task 6: The `parse_redact` stage

**Files:**
- Create: `backend/app/documents/ingest.py`
- Modify: `backend/app/documents/dao.py` (append element functions)
- Test: `backend/tests/test_documents_ingest.py`

**Interfaces:**
- Consumes: `parse_pdf`, `PiiDetector`, `apply_redaction`, `dao.save_tokens`, `dao.get_version`, `dao.append_event`, `store.original_path`.
- Produces:
  - `dao.list_elements(session, version_id: UUID) -> list[DocumentElement]` (ordered by ordinal)
  - `dao.get_document_for_version(session, version_id: UUID) -> Document`
  - `dao.parsed_detail(session, version_id: UUID) -> dict` (the `parsed` event's detail; `{}` if none)
  - `ingest.parse_and_redact(session, version_id: UUID, *, parser: Callable[[Path], ParsedDocument], detector: PiiDetector, store_root: Path, hmac_key: str, vault_key: str) -> None` — writes elements + tokens + `parsed` event in one commit; returns early (no writes) if elements already exist.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_documents_ingest.py`:
```python
from pathlib import Path

import pytest

from app import config
from app.documents import dao
from app.documents.ingest import parse_and_redact
from app.documents.parse import ParsedDocument, ParsedElement, parse_pdf
from app.documents.redact import PiiDetector, PiiSpan
from app.documents.sniff import PdfFacts
from app.documents.types import ElementKind, VersionStage

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
RAW_PII = ("Marie Tremblay", "130 692 544", "marie.tremblay@example.com", "514-555-0142")


class NameOnlyDetector:
    def detect(self, text: str) -> list[PiiSpan]:
        start = text.find("Marie Tremblay")
        return [] if start < 0 else [PiiSpan(start, start + len("Marie Tremblay"), "PERSON", 0.9)]


def _fake_parser(_path: Path) -> ParsedDocument:
    return ParsedDocument(
        elements=(
            ParsedElement(ElementKind.heading, "3. Fees", ("3. Fees",), 1, 1),
            ParsedElement(ElementKind.paragraph, "Client Marie Tremblay pays quarterly.", ("3. Fees",), 1, 2),
        ),
        page_grades={1: "GOOD", 2: "EXCELLENT"},
        parser_version="fake 1",
    )


def _stored_version(db_session, tenant_id):
    data = FIXTURE.read_bytes()
    return dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="tremblay-ima", title="Tremblay IMA", source_url=None,
        data=data, facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version


def _run(db_session, version_id, parser=_fake_parser, detector=None):
    parse_and_redact(
        db_session, version_id, parser=parser, detector=detector or NameOnlyDetector(),
        store_root=config.DOCUMENT_STORE_DIR, hmac_key=config.PII_HMAC_KEY, vault_key=config.PII_VAULT_KEY,
    )


def test_stage_writes_redacted_elements_tokens_and_parsed_event(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id)
    elements = dao.list_elements(db_session, version.id)
    assert [e.ordinal for e in elements] == [0, 1]
    assert "Marie Tremblay" not in elements[1].text_redacted
    assert (elements[1].page_start, elements[1].page_end) == (1, 2)
    events = dao.version_events(db_session, version.id)
    assert [e.stage for e in events] == [VersionStage.stored, VersionStage.parsed]
    assert events[-1].detail["page_grades"] == {"1": "GOOD", "2": "EXCELLENT"}
    assert events[-1].detail["pii_token_count"] == 1


def test_stage_is_a_noop_when_already_parsed(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id)
    _run(db_session, version.id)
    assert len(dao.version_events(db_session, version.id)) == 2


@pytest.mark.slow
def test_real_pipeline_leaves_no_raw_pii_in_elements(db_session, tenant_id):
    version = _stored_version(db_session, tenant_id)
    _run(db_session, version.id, parser=parse_pdf, detector=PiiDetector())
    stored_text = "\n".join(e.text_redacted for e in dao.list_elements(db_session, version.id))
    for value in RAW_PII:
        assert value not in stored_text
    assert "Ontario" in stored_text and "0.85%" in stored_text
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_documents_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.documents.ingest'`.

- [ ] **Step 3: Add the element functions to the DAO**

Append to `backend/app/documents/dao.py` (add `DocumentElement` to the models import):
```python
def list_elements(session: Session, version_id: uuid.UUID) -> list[DocumentElement]:
    return list(
        session.scalars(select(DocumentElement).where(DocumentElement.version_id == version_id).order_by(DocumentElement.ordinal))
    )


def get_document_for_version(session: Session, version_id: uuid.UUID) -> Document:
    return session.scalars(
        select(Document).join(DocumentVersion, DocumentVersion.document_id == Document.id).where(DocumentVersion.id == version_id)
    ).one()


def parsed_detail(session: Session, version_id: uuid.UUID) -> dict:
    event = session.scalars(
        select(VersionEvent)
        .where(VersionEvent.version_id == version_id, VersionEvent.stage == VersionStage.parsed)
        .order_by(VersionEvent.id.desc())
    ).first()
    return {} if event is None else dict(event.detail)
```

- [ ] **Step 4: Implement the stage**

`backend/app/documents/ingest.py`:
```python
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from app.documents import dao, store
from app.documents.models import DocumentElement
from app.documents.parse import ParsedDocument
from app.documents.redact import PiiDetector, apply_redaction
from app.documents.types import VersionStage


def parse_and_redact(
    session: Session,
    version_id: uuid.UUID,
    *,
    parser: Callable[[Path], ParsedDocument],
    detector: PiiDetector,
    store_root: Path,
    hmac_key: str,
    vault_key: str,
) -> None:
    """Parse and redact in one step: Docling's raw text holds PII and is never persisted."""
    version = dao.get_version(session, version_id)
    tenant_id = dao.get_document_for_version(session, version_id).tenant_id
    if dao.list_elements(session, version_id):
        return
    session.commit()  # end the read transaction before minutes of CPU work

    parsed = parser(store.original_path(store_root, version.file_sha256))
    tokens: dict[str, tuple[str, str]] = {}
    for ordinal, element in enumerate(parsed.elements):
        redaction = apply_redaction(element.text, detector.detect(element.text), tenant_id, hmac_key)
        tokens.update(redaction.tokens)
        session.add(DocumentElement(
            version_id=version_id, ordinal=ordinal, kind=element.kind, section_path=list(element.section_path),
            page_start=element.page_start, page_end=element.page_end, text_redacted=redaction.text,
            parser_version=parsed.parser_version,
        ))
    dao.save_tokens(session, tenant_id, tokens, vault_key)
    dao.append_event(session, version_id, VersionStage.parsed, {
        "element_count": len(parsed.elements),
        "pii_token_count": len(tokens),
        "page_grades": {str(page): grade for page, grade in parsed.page_grades.items()},
        "parser_version": parsed.parser_version,
    })
    session.commit()
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_documents_ingest.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add app/documents/ingest.py app/documents/dao.py tests/test_documents_ingest.py
git commit -m "feat(documents): add the parse-and-redact stage"
```

---

### Task 7: Pipeline sequencing and the worker

**Files:**
- Create: `backend/app/ingestion_pipeline.py`, `backend/scripts/ingestion_worker.py`
- Test: `backend/tests/test_ingestion_pipeline.py`

**Interfaces:**
- Consumes: `dao.version_events`, `dao.append_event`, `dao.all_version_ids`, `VersionStage`.
- Produces:
  - `StageSpec(name: str, requires: VersionStage, produces: VersionStage)`
  - `PARSE_REDACT`, `PIPELINE: tuple[StageSpec, ...]` — plans 3 and 2 extend it with `INDEX` then `EXTRACT`
  - `MAX_STAGE_ATTEMPTS = 3`
  - `StageRunner = Callable[[Session, uuid.UUID], None]`
  - `next_stage(pipeline, events) -> StageSpec | None`
  - `VersionStatus(state: Literal["processing", "ready", "failed"], note: str | None)`; `version_status(pipeline, events) -> VersionStatus`
  - `run_pending(session_factory: sessionmaker, runners: Mapping[str, StageRunner], pipeline=PIPELINE) -> int`
  - `scripts/ingestion_worker.py`: `build_runners() -> dict[str, StageRunner]`, `main()` with `--once`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_ingestion_pipeline.py`:
```python
from pathlib import Path

from app import config
from app.documents import dao
from app.documents.sniff import PdfFacts
from app.documents.types import VersionStage
from app.ingestion_pipeline import (
    MAX_STAGE_ATTEMPTS, PARSE_REDACT, StageSpec, next_stage, run_pending, version_status,
)

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"
INDEX = StageSpec("index", VersionStage.parsed, VersionStage.indexed)
EXTRACT = StageSpec("extract", VersionStage.parsed, VersionStage.extracted)
PIPELINE = (PARSE_REDACT, INDEX, EXTRACT)


class Ev:  # stands in for VersionEvent in pure tests
    def __init__(self, stage, detail=None):
        self.stage, self.detail = stage, detail or {}


def test_next_stage_follows_requirements_not_list_position():
    assert next_stage(PIPELINE, [Ev(VersionStage.stored)]) is PARSE_REDACT
    parsed = [Ev(VersionStage.stored), Ev(VersionStage.parsed)]
    assert next_stage(PIPELINE, parsed) is INDEX
    assert next_stage(PIPELINE, parsed + [Ev(VersionStage.indexed)]) is EXTRACT
    done = parsed + [Ev(VersionStage.indexed), Ev(VersionStage.extracted)]
    assert next_stage(PIPELINE, done) is None
    assert version_status(PIPELINE, done).state == "ready"


def test_failed_stage_is_retried_then_given_up():
    events = [Ev(VersionStage.stored)]
    for attempt in range(MAX_STAGE_ATTEMPTS):
        assert next_stage(PIPELINE, events) is PARSE_REDACT
        events.append(Ev(VersionStage.failed, {"stage": "parse_redact", "error_type": "Boom", "message": "x"}))
    assert next_stage(PIPELINE, events) is None
    status = version_status(PIPELINE, events)
    assert status.state == "failed"
    assert "parse_redact" in status.note and "Boom" in status.note


def test_a_failed_index_does_not_block_extraction():
    events = [Ev(VersionStage.stored), Ev(VersionStage.parsed)] + [
        Ev(VersionStage.failed, {"stage": "index", "error_type": "Timeout", "message": ""})
    ] * MAX_STAGE_ATTEMPTS
    assert next_stage(PIPELINE, events) is EXTRACT


def _stored(db_session, tenant_id):
    data = FIXTURE.read_bytes()
    return dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="tremblay-ima", title="IMA", source_url=None,
        data=data, facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version


def test_run_pending_records_a_raising_stage_as_failed(session_factory, db_session, tenant_id):
    version = _stored(db_session, tenant_id)

    def boom(_session, version_id):
        if version_id == version.id:
            raise ValueError("parser exploded")

    run_pending(session_factory, {"parse_redact": boom}, pipeline=(PARSE_REDACT,))
    events = dao.version_events(db_session, version.id)
    assert events[-1].stage is VersionStage.failed
    assert events[-1].detail == {"stage": "parse_redact", "error_type": "ValueError", "message": "parser exploded"}


def test_run_pending_runs_the_next_stage(session_factory, db_session, tenant_id):
    version = _stored(db_session, tenant_id)

    def fake_parse(session, version_id):
        if version_id == version.id:
            dao.append_event(session, version_id, VersionStage.parsed, {})
            session.commit()

    run_pending(session_factory, {"parse_redact": fake_parse}, pipeline=(PARSE_REDACT,))
    assert dao.version_events(db_session, version.id)[-1].stage is VersionStage.parsed
```
(`run_pending` walks every version in the test database, including other tests' rows; the fake runners act only on their own `version.id`, and `boom`/`fake_parse` returning without writing for other versions is harmless.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_ingestion_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion_pipeline'`.

- [ ] **Step 3: Implement the pipeline**

`backend/app/ingestion_pipeline.py`:
```python
"""Sequences ingestion stages across packages. It is the "main" wiring: documents, retrieval and
contracts never import each other; only this module knows the order."""
import logging
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.documents import dao as documents_dao
from app.documents.types import VersionStage

logger = logging.getLogger(__name__)
MAX_STAGE_ATTEMPTS = 3
MAX_ERROR_MESSAGE_CHARS = 500
StageRunner = Callable[[Session, uuid.UUID], None]


@dataclass(frozen=True)
class StageSpec:
    name: str
    requires: VersionStage
    produces: VersionStage


PARSE_REDACT = StageSpec("parse_redact", VersionStage.stored, VersionStage.parsed)
PIPELINE: tuple[StageSpec, ...] = (PARSE_REDACT,)


class EventLike(Protocol):
    stage: VersionStage
    detail: dict


@dataclass(frozen=True)
class VersionStatus:
    state: Literal["processing", "ready", "failed"]
    note: str | None


def _failures(events: Sequence[EventLike]) -> Counter:
    return Counter(e.detail.get("stage") for e in events if e.stage is VersionStage.failed)


def next_stage(pipeline: Sequence[StageSpec], events: Sequence[EventLike]) -> StageSpec | None:
    reached = {e.stage for e in events}
    failures = _failures(events)
    for spec in pipeline:
        if spec.produces not in reached and spec.requires in reached and failures[spec.name] < MAX_STAGE_ATTEMPTS:
            return spec
    return None


def version_status(pipeline: Sequence[StageSpec], events: Sequence[EventLike]) -> VersionStatus:
    reached = {e.stage for e in events}
    failures = _failures(events)
    exhausted = [s for s in pipeline if s.produces not in reached and failures[s.name] >= MAX_STAGE_ATTEMPTS]
    if exhausted:
        last = next(e for e in reversed(events) if e.stage is VersionStage.failed and e.detail.get("stage") == exhausted[0].name)
        return VersionStatus("failed", f"{exhausted[0].name} failed: {last.detail.get('error_type')} {last.detail.get('message', '')}".strip())
    pending = [s for s in pipeline if s.produces not in reached]
    if pending:
        return VersionStatus("processing", f"waiting for {pending[0].name}")
    return VersionStatus("ready", None)


def _run_next(session_factory: sessionmaker, runners: Mapping[str, StageRunner], pipeline: Sequence[StageSpec], version_id: uuid.UUID) -> bool:
    lock = text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))")
    unlock = text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))")
    with session_factory.kw["bind"].connect() as lock_connection:  # the lease; separate from the work session
        if not lock_connection.execute(lock, {"key": str(version_id)}).scalar():
            return False  # another worker holds this version
        try:
            with session_factory() as session:
                spec = next_stage(pipeline, documents_dao.version_events(session, version_id))
                if spec is None or spec.name not in runners:
                    return False
                try:
                    runners[spec.name](session, version_id)
                except Exception as exc:  # every stage failure is recorded, whatever its type; nothing is lost silently
                    session.rollback()
                    logger.exception("stage %s failed for version %s", spec.name, version_id)
                    documents_dao.append_event(session, version_id, VersionStage.failed, {
                        "stage": spec.name, "error_type": type(exc).__name__, "message": str(exc)[:MAX_ERROR_MESSAGE_CHARS],
                    })
                    session.commit()
                return True
        finally:
            lock_connection.execute(unlock, {"key": str(version_id)})


def run_pending(session_factory: sessionmaker, runners: Mapping[str, StageRunner], pipeline: Sequence[StageSpec] = PIPELINE) -> int:
    """One pass over all versions, one stage each. Returns how many stages ran."""
    with session_factory() as session:
        version_ids = documents_dao.all_version_ids(session)
    return sum(_run_next(session_factory, runners, pipeline, version_id) for version_id in version_ids)
```

- [ ] **Step 4: Implement the worker script**

`backend/scripts/ingestion_worker.py`:
```python
"""Ingestion worker: the only process that loads Docling and spaCy.
Run from backend/:  .venv/bin/python scripts/ingestion_worker.py   (add --once for a single pass)"""
import argparse
import logging
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.documents.ingest import parse_and_redact  # noqa: E402
from app.documents.parse import parse_pdf  # noqa: E402
from app.documents.redact import PiiDetector  # noqa: E402
from app.ingestion_pipeline import PIPELINE, StageRunner, run_pending  # noqa: E402
from app.ledger.db import SessionLocal  # noqa: E402

POLL_SECONDS = 2.0


def build_runners() -> dict[str, StageRunner]:
    return {
        "parse_redact": partial(
            parse_and_redact, parser=parse_pdf, detector=PiiDetector(), store_root=config.DOCUMENT_STORE_DIR,
            hmac_key=config.require("PII_HMAC_KEY"), vault_key=config.require("PII_VAULT_KEY"),
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process pending stages once, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    runners = build_runners()
    # ponytail: one worker, one stage at a time (RAM budget); the advisory lock makes more workers safe when needed
    while True:
        ran = run_pending(SessionLocal, runners, PIPELINE)
        if args.once:
            logging.info("ran %d stage(s)", ran)
            return
        if ran == 0:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_ingestion_pipeline.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add app/ingestion_pipeline.py scripts/ingestion_worker.py tests/test_ingestion_pipeline.py
git commit -m "feat(ingestion): sequence stages from the event log in a separate worker process"
```

---

### Task 8: Document endpoints

**Files:**
- Create: `backend/app/routes/documents.py`
- Modify: `backend/app/main.py`, `backend/app/documents/dao.py` (listing queries)
- Test: `backend/tests/test_api_documents.py`

**Interfaces:**
- Consumes: `inspect_pdf`, `register_upload`, `version_status`, `PIPELINE`, `dao.reveal`, `store.original_path`.
- Produces:
  - `dao.DocumentRow(document: Document, version: DocumentVersion, events: list[VersionEvent], element_count: int)`
  - `dao.list_documents(session, tenant_id: UUID) -> list[DocumentRow]` (current = highest version)
  - `dao.get_document_row(session, tenant_id: UUID, document_id: UUID) -> DocumentRow` (raises `DocumentNotFound`)
  - `dao.get_version_by_number(session, tenant_id: UUID, document_id: UUID, version: int) -> DocumentVersion`
  - HTTP: `POST /documents` (multipart: `file`, `document_key`, `title`, `source_url?`, `household_id?`) → 202/200 `UploadOut`; `GET /documents` → `list[DocumentOut]`; `GET /documents/{id}` → `DocumentDetailOut`; `GET /documents/{id}/versions/{version}/file` → `application/pdf`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_api_documents.py`:
```python
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
    assert response.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_api_documents.py -v`
Expected: FAIL with 404s / `AttributeError` (router not registered).

- [ ] **Step 3: Add listing queries to the DAO**

Append to `backend/app/documents/dao.py` (add `DocumentNotFound` to the errors import):
```python
@dataclass(frozen=True)
class DocumentRow:
    document: Document
    version: DocumentVersion
    events: list[VersionEvent]
    element_count: int


def _row(session: Session, document: Document) -> DocumentRow:
    version = session.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document.id).order_by(DocumentVersion.version.desc())
    ).first()
    count = session.scalar(select(func.count()).select_from(DocumentElement).where(DocumentElement.version_id == version.id))
    return DocumentRow(document, version, version_events(session, version.id), count)


def list_documents(session: Session, tenant_id: uuid.UUID) -> list[DocumentRow]:
    # ponytail: N+1 queries per document; fine for a handful of contracts, one grouped query when it isn't
    documents = session.scalars(select(Document).where(Document.tenant_id == tenant_id).order_by(Document.created_at.desc()))
    return [_row(session, document) for document in documents]


def get_document_row(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> DocumentRow:
    document = session.get(Document, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise DocumentNotFound(f"Document {document_id} does not exist.")
    return _row(session, document)


def get_version_by_number(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID, version: int) -> DocumentVersion:
    get_document_row(session, tenant_id, document_id)  # tenant check
    row = session.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == document_id, DocumentVersion.version == version)
    ).one_or_none()
    if row is None:
        raise VersionNotFound(f"Document {document_id} has no version {version}.")
    return row
```

- [ ] **Step 4: Implement the router and register it**

`backend/app/routes/documents.py`:
```python
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import config
from app.deps import DECIDED_BY, get_session, get_tenant_id
from app.documents import dao, store
from app.documents.sniff import MAX_UPLOAD_BYTES, inspect_pdf
from app.ingestion_pipeline import PIPELINE, version_status

router = APIRouter(prefix="/documents", tags=["documents"])
SessionDep = Annotated[Session, Depends(get_session)]
TenantDep = Annotated[uuid.UUID, Depends(get_tenant_id)]
PREVIEW_ELEMENTS = 5
DOCUMENT_KEY_PATTERN = r"^[a-z0-9][a-z0-9-]{1,63}$"


class UploadOut(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    version: int
    status_url: str


class EventOut(BaseModel):
    stage: str
    at: datetime
    detail: dict


class DocumentOut(BaseModel):
    id: uuid.UUID
    document_key: str
    title: str
    source_url: str | None
    household_id: uuid.UUID | None
    version: int
    version_id: uuid.UUID
    page_count: int
    byte_size: int
    file_sha256: str
    uploaded_at: datetime
    element_count: int
    status: Literal["processing", "ready", "failed"]
    status_note: str | None
    events: list[EventOut]


class ElementPreviewOut(BaseModel):
    ordinal: int
    kind: str
    section_path: list[str]
    page_start: int
    page_end: int
    text: str


class DocumentDetailOut(DocumentOut):
    preview: list[ElementPreviewOut]


def _out(row: dao.DocumentRow) -> dict:
    status = version_status(PIPELINE, row.events)
    return dict(
        id=row.document.id, document_key=row.document.document_key, title=row.document.title,
        source_url=row.document.source_url, household_id=row.document.household_id, version=row.version.version, version_id=row.version.id,
        page_count=row.version.page_count, byte_size=row.version.byte_size, file_sha256=row.version.file_sha256,
        uploaded_at=row.version.created_at, element_count=row.element_count, status=status.state,
        status_note=status.note,
        events=[EventOut(stage=e.stage.value, at=e.created_at, detail=e.detail) for e in row.events],
    )


@router.post("", status_code=202, response_model=UploadOut)
def upload_document(
    response: Response,
    session: SessionDep,
    tenant_id: TenantDep,
    file: Annotated[UploadFile, File()],
    document_key: Annotated[str, Form(pattern=DOCUMENT_KEY_PATTERN)],
    title: Annotated[str, Form(min_length=1, max_length=300)],
    source_url: Annotated[str | None, Form(max_length=2000)] = None,
    household_id: Annotated[uuid.UUID | None, Form()] = None,
) -> UploadOut:
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    result = dao.register_upload(
        session, tenant_id=tenant_id, document_key=document_key, title=title, source_url=source_url,
        data=data, facts=inspect_pdf(data), uploaded_by=DECIDED_BY, store_root=config.DOCUMENT_STORE_DIR,
        household_id=household_id,
    )
    if not result.created:
        response.status_code = 200
    return UploadOut(document_id=result.document.id, version_id=result.version.id, version=result.version.version,
                     status_url=f"/documents/{result.document.id}")


@router.get("", response_model=list[DocumentOut])
def list_documents(session: SessionDep, tenant_id: TenantDep) -> list[DocumentOut]:
    return [DocumentOut(**_out(row)) for row in dao.list_documents(session, tenant_id)]


@router.get("/{document_id}", response_model=DocumentDetailOut)
def get_document(document_id: uuid.UUID, session: SessionDep, tenant_id: TenantDep) -> DocumentDetailOut:
    row = dao.get_document_row(session, tenant_id, document_id)
    elements = dao.list_elements(session, row.version.id)[:PREVIEW_ELEMENTS]
    # ponytail: detokenises for the single demo user; gate on the principal's permissions once auth exists
    texts = dao.reveal(session, tenant_id, [e.text_redacted for e in elements], config.require("PII_VAULT_KEY"))
    preview = [
        ElementPreviewOut(ordinal=e.ordinal, kind=e.kind.value, section_path=e.section_path,
                          page_start=e.page_start, page_end=e.page_end, text=text)
        for e, text in zip(elements, texts)
    ]
    return DocumentDetailOut(**_out(row), preview=preview)


@router.get("/{document_id}/versions/{version}/file")
def get_original_file(document_id: uuid.UUID, version: int, session: SessionDep, tenant_id: TenantDep) -> FileResponse:
    # ponytail: contains PII; behind the demo-user dependency only until real authorization exists
    row = dao.get_version_by_number(session, tenant_id, document_id, version)
    return FileResponse(store.original_path(config.DOCUMENT_STORE_DIR, row.file_sha256), media_type="application/pdf")
```
In `backend/app/main.py`, change the routes import to include `documents` and add `app.include_router(documents.router)`.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_api_documents.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all previous tests plus the new ones pass.

- [ ] **Step 7: Commit**

```bash
git add app/routes/documents.py app/main.py app/documents/dao.py tests/test_api_documents.py
git commit -m "feat(documents): add upload, list, detail and original-file endpoints"
```

---

### Task 9: EDGAR samples, docs and a live run

**Files:**
- Create: `backend/scripts/prepare_samples.py`
- Modify: `README.md`, `CLAUDE.md`, `backend/.env.example` (already has `SEC_USER_AGENT` from Task 1)

**Interfaces:**
- Consumes: the running API (`POST /documents`) when `--upload` is given.
- Produces: `backend/var/samples/<key>.pdf` + `manifest.json`; README instructions.

- [ ] **Step 1: Write the sample script**

`backend/scripts/prepare_samples.py`:
```python
"""Download single-fund EDGAR advisory agreements, render them to PDF (the canonical file, so every
citation has a page), and optionally upload them plus the synthetic client agreement.
Run from backend/:  SEC_USER_AGENT="Name email" .venv/bin/python scripts/prepare_samples.py [--upload http://127.0.0.1:8000]"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BACKEND_DIR / "var" / "samples"
CHROME = "google-chrome"
SYNTHETIC = BACKEND_DIR / "tests" / "fixtures" / "documents" / "client_agreement.pdf"
SAMPLES = [
    {"key": "nomura-tax-free-colorado-ima", "title": "Voyageur Mutual Funds II / Delaware Management — IMA (2025)",
     "url": "https://www.sec.gov/Archives/edgar/data/809872/000113322825014217/vmfii-efp21465_ex99d1.htm"},
    {"key": "aim-global-trends-advisory", "title": "AIM Global Trends Fund — Master Investment Advisory Agreement",
     "url": "https://www.sec.gov/Archives/edgar/data/1021453/000095012902002087/h95945ex99-d.txt"},
    {"key": "calamos-emerging-market-equity", "title": "Calamos Emerging Market Equity Fund — Management Agreement notice",
     "url": "https://www.sec.gov/Archives/edgar/data/826732/000119312513480695/d640945dex99d15.htm"},
]
TIMEOUT_SECONDS = 60
# Same derivation as scripts/seed_demo.py, so the synthetic agreement links to the seeded Tremblay household.
TREMBLAY_HOUSEHOLD_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "ledger-lens-demo/hh_tremblay"))


def fetch(url: str, user_agent: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})  # SEC requires a named agent
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def render_pdf(source: Path, pdf: Path) -> None:
    subprocess.run(
        [CHROME, "--headless=new", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", source.as_uri()],
        check=True, timeout=TIMEOUT_SECONDS, capture_output=True,
    )


def upload(base_url: str, key: str, title: str, pdf: Path, source_url: str | None, household_id: str | None = None) -> None:
    data = {"document_key": key, "title": title} | ({"source_url": source_url} if source_url else {})
    data |= {"household_id": household_id} if household_id else {}
    response = httpx.post(f"{base_url}/documents", data=data,
                          files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    print(f"uploaded {key}: {response.status_code} {response.json()['status_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", metavar="BASE_URL", help="also POST each PDF to the running API")
    args = parser.parse_args()
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        sys.exit("Set SEC_USER_AGENT to 'Your Name your.email@example.com' (SEC fair-access policy).")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for sample in SAMPLES:
        suffix = ".txt" if sample["url"].endswith(".txt") else ".html"
        source = OUT_DIR / f"{sample['key']}{suffix}"
        pdf = OUT_DIR / f"{sample['key']}.pdf"
        source.write_bytes(fetch(sample["url"], user_agent))
        render_pdf(source, pdf)
        manifest.append(sample | {"pdf": pdf.name})
        if args.upload:
            upload(args.upload, sample["key"], sample["title"], pdf, sample["url"])
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    if args.upload:
        upload(args.upload, "tremblay-ima", "Tremblay household — Investment Management Agreement (synthetic)",
               SYNTHETIC, None, TREMBLAY_HOUSEHOLD_ID)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update README**

In `README.md`, after the "Document-intelligence models (one-time download)" section, add:
````markdown
### Document ingestion (local run)

1. Set `PII_HMAC_KEY` and `PII_VAULT_KEY` in `backend/.env` (generation commands are in `.env.example`).
2. Start the API: `.venv/bin/uvicorn app.main:app --reload`
3. Start the worker in a second terminal: `.venv/bin/python scripts/ingestion_worker.py`
   (the only process that loads Docling and spaCy; the API stays light)
4. Load the samples: `SEC_USER_AGENT="Name email" .venv/bin/python scripts/prepare_samples.py --upload http://127.0.0.1:8000`
   — three single-fund EDGAR advisory agreements (rendered to PDF so every citation has a page)
   plus the synthetic Tremblay agreement (PII + a deliberate fee mismatch with the seeded billing schedule).
5. Watch status: `curl -s http://127.0.0.1:8000/documents | python -m json.tool`

Scanned PDFs (no text layer) and non-PDF files are rejected at upload with a 422.
Multi-fund EDGAR exhibits are out of scope for now: the extraction schema models one fee schedule per contract.
````

- [ ] **Step 3: Update the CLAUDE.md stack table**

In `CLAUDE.md`, replace the rows for OCR, DB and LLM gateway with:
```markdown
| DB | PostgreSQL 18 — localhost for dev (roles: ledger_owner migrates, ledger_app runs the API with SELECT/INSERT only, plus DELETE on the derived `element_search` table), Aurora PostgreSQL for the demo/deploy run (verify 18 support before Epic 1.5) |
| Parsing / PII | Docling (local) + Presidio analyzer with deterministic HMAC tokens; runs only in `scripts/ingestion_worker.py` |
| Vector store / search | Pinecone (dense) + Postgres full-text search, merged with reciprocal rank fusion |
| LLM | OpenAI via LangChain `ChatOpenAI` (structured output) and LangGraph (chat agent) |
```
and add `app/documents`, `app/contracts`, `app/retrieval`, `app/assistant` to the Layering line's package list (`No direct DB access outside each package's own dao.py`).

- [ ] **Step 4: Live verification**

With `./scripts/db_up.sh` done, the seeded demo (`scripts/seed_demo.py`), `.env` keys set, API and worker running:
```bash
SEC_USER_AGENT="Your Name you@example.com" .venv/bin/python scripts/prepare_samples.py --upload http://127.0.0.1:8000
sleep 120
curl -s http://127.0.0.1:8000/documents | python -c "import json,sys; [print(d['document_key'], d['status'], d['element_count']) for d in json.load(sys.stdin)]"
```
Expected: 4 documents, each `ready` with `element_count > 0` (plan 1's pipeline has only `parse_redact`; plans 3 and 2 add `index` and `extract`). If a sample fails, read `status_note` and the worker log; fix and re-run the worker (failed stages retry up to 3 times).
Then: `curl -s http://127.0.0.1:8000/documents/<tremblay id> | python -m json.tool` shows the preview with the real names revealed, and `psql` on `document_elements` for that version shows tokens only.

- [ ] **Step 5: Commit**

```bash
git add scripts/prepare_samples.py ../README.md ../CLAUDE.md
git commit -m "docs(ingestion): add EDGAR sample loader, worker instructions and stack update"
```
