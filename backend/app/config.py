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
