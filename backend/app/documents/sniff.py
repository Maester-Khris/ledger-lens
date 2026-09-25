import io
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app import config
from app.documents.errors import UploadRejected

PDF_MAGIC = b"%PDF-"
MAX_UPLOAD_BYTES = config.MAX_UPLOAD_BYTES
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
    except (PdfReadError, ValueError) as exc:
        raise UploadRejected("The PDF could not be read.") from exc
    if not pages:
        raise UploadRejected("The PDF has no pages.")
    if image_only / len(pages) > MAX_IMAGE_ONLY_PAGE_SHARE:
        raise UploadRejected("The PDF has no usable text layer; scanned documents are not supported yet.")
    return PdfFacts(page_count=len(pages), byte_size=len(data))
