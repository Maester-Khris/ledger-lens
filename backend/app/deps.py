import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app import config
from app.assistant import dao as assistant_dao
from app.errors import GuestRequired
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



def get_overlay_guest(guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]) -> uuid.UUID | None:
    """Reads: the guest whose overlay applies in the public demo. None (flag off, or no known guest) = shared view."""
    return guest_id if config.DEMO_MODE else None


def require_overlay_guest(guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]) -> uuid.UUID | None:
    """Decision writes: in the public demo a known guest is required. None (flag off) = today's real tables."""
    if not config.DEMO_MODE:
        return None
    if guest_id is None:
        raise GuestRequired("Send the X-Guest-Id of a known guest (POST /guests) to decide in the public demo.")
    return guest_id
