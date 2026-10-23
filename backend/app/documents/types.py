from dataclasses import dataclass
import enum

# Pure types shared by models, DAO and pure logic. No SQLAlchemy or FastAPI imports here.


@dataclass(frozen=True)
class Box:
    page_no: int
    l: float
    t: float
    r: float
    b: float
    coord_origin: str   # "BOTTOMLEFT" or "TOPLEFT", as Docling reports it; PDF points


class DocumentType(str, enum.Enum):
    contract = "contract"


class VersionStage(str, enum.Enum):
    stored = "stored"
    parsed = "parsed"
    indexed = "indexed"
    extracted = "extracted"
    verified = "verified"
    failed = "failed"


class ElementKind(str, enum.Enum):
    heading = "heading"
    paragraph = "paragraph"
    table = "table"
