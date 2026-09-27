import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.assistant import dao as assistant_dao
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

def parse_guest_header(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def get_guest_id(
    session: Annotated[Session, Depends(get_session)],
    tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)],
    x_guest_id: Annotated[str | None, Header()] = None,
) -> uuid.UUID | None:
    """Attribution only: a missing, malformed or unknown id resolves to None, never an error."""
    guest_id = parse_guest_header(x_guest_id)
    return None if guest_id is None else assistant_dao.touch_guest(session, tenant_id, guest_id)


def decided_by(guest_id: uuid.UUID | None) -> str:
    return f"guest:{str(guest_id)[:8]}" if guest_id is not None else DECIDED_BY
