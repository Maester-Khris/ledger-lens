import uuid
from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID

# ponytail: no authentication yet; the acting user is fixed. Replace with the authenticated principal.
DECIDED_BY = "demo_user"


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_tenant_id() -> uuid.UUID:
    # ponytail: single fixed demo tenant until authentication exists; resolve it from the principal then.
    return DEMO_TENANT_ID
