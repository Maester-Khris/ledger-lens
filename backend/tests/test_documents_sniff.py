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
