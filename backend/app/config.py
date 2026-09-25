import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]

# backend/.env, wherever the command runs from. Real environment variables win over the file.
load_dotenv(BACKEND_DIR / ".env")


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


_LOCAL = "localhost:5432"

# Runtime app role: SELECT/INSERT only (see migration 0003/0004 grants).
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"postgresql+psycopg://ledger_app:localdev@{_LOCAL}/ledger_dev",
)

# Schema owner: runs migrations only.
MIGRATION_DATABASE_URL = os.environ.get(
    "MIGRATION_DATABASE_URL",
    f"postgresql+psycopg://ledger_owner:localdev@{_LOCAL}/ledger_dev",
)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    f"postgresql+psycopg://ledger_app:localdev@{_LOCAL}/ledger_test",
)

TEST_OWNER_DATABASE_URL = os.environ.get(
    "TEST_OWNER_DATABASE_URL",
    f"postgresql+psycopg://ledger_owner:localdev@{_LOCAL}/ledger_test",
)

MIGRATION_ROUNDTRIP_DATABASE_URL = os.environ.get(
    "MIGRATION_ROUNDTRIP_DATABASE_URL",
    f"postgresql+psycopg://ledger_owner:localdev@{_LOCAL}/ledger_migration_test",
)

# Original PDFs, content-addressed. Holds raw PII: never commit, back up like the database.
# Relative paths resolve against backend/.
DOCUMENT_STORE_DIR = BACKEND_DIR / os.environ.get("DOCUMENT_STORE_DIR", "var/documents")

# Secrets: no defaults on purpose. Required only by code paths that tokenise or reveal PII.
PII_HMAC_KEY = os.environ.get("PII_HMAC_KEY")
PII_VAULT_KEY = os.environ.get("PII_VAULT_KEY")  # a Fernet key: Fernet.generate_key().decode()


def require(name: str) -> str:
    value = globals().get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; see backend/.env.example")
    return value


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX = os.environ.get("PINECONE_INDEX", "contracts")
# Exact snapshot, never an alias: tool_invocations and chat_turns record it for audit.
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4.1-2025-04-14")
EXTRACTION_MODEL = os.environ.get("EXTRACTION_MODEL", CHAT_MODEL)
# Changing either means recreating the Pinecone index and re-indexing every document.
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = _int("EMBEDDING_DIMENSIONS", 1536)

# LLM call limits
CHAT_TIMEOUT_SECONDS = _float("CHAT_TIMEOUT_SECONDS", 30)
EMBEDDING_TIMEOUT_SECONDS = _float("EMBEDDING_TIMEOUT_SECONDS", 15)
EXTRACTION_TIMEOUT_SECONDS = _float("EXTRACTION_TIMEOUT_SECONDS", 60)
LLM_MAX_RETRIES = _int("LLM_MAX_RETRIES", 3)
CHAT_TURN_TIMEOUT_SECONDS = _float("CHAT_TURN_TIMEOUT_SECONDS", 60)

# Pinecone serverless placement (used when creating the index) and per-call timeout
PINECONE_CLOUD = os.environ.get("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.environ.get("PINECONE_REGION", "us-east-1")
PINECONE_TIMEOUT_SECONDS = _float("PINECONE_TIMEOUT_SECONDS", 10)

# Retrieval tuning. MIN_DENSE_SIMILARITY is calibrated on the golden set (tests/eval).
SEARCH_CANDIDATES = _int("SEARCH_CANDIDATES", 20)
MIN_DENSE_SIMILARITY = _float("MIN_DENSE_SIMILARITY", 0.30)

# Ingestion
MAX_UPLOAD_BYTES = _int("MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
WORKER_POLL_SECONDS = _float("WORKER_POLL_SECONDS", 2.0)
