import os

from dotenv import load_dotenv

load_dotenv()

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
