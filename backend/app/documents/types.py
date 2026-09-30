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
