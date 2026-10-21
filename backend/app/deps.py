import logging
import math
import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app import config
from app.assistant import admission
from app.assistant import dao as assistant_dao
from app.assistant.admission import Slot
from app.errors import AssistantBusy, GuestRequired, RateLimited
from app.ledger.db import SessionLocal
from app.ledger.types import DEMO_TENANT_ID
from app.rate_limit import RedisWindowLimiter, SlidingWindowLimiter, admit

logger = logging.getLogger(__name__)

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


def build_chat_limits() -> tuple[RedisWindowLimiter, RedisWindowLimiter] | tuple[SlidingWindowLimiter, SlidingWindowLimiter]:
    """Public demo (P3, N5): one pair of chat windows, per guest and per client IP; in Redis when REDIS_URL is set
    (shared by every worker and replica), else in this process."""
    if config.REDIS_URL:
        # Only a deployment with Redis needs the client.
        import redis

        client = redis.Redis.from_url(
            config.REDIS_URL,
            socket_timeout=config.REDIS_TIMEOUT_SECONDS,
            socket_connect_timeout=config.REDIS_TIMEOUT_SECONDS,
        )
        return (
            RedisWindowLimiter(client, "chat:guest", config.CHAT_LIMIT_PER_GUEST, config.CHAT_LIMIT_WINDOW_SECONDS),
            RedisWindowLimiter(client, "chat:ip", config.CHAT_LIMIT_PER_IP, config.CHAT_LIMIT_WINDOW_SECONDS),
        )
    return (
        SlidingWindowLimiter(config.CHAT_LIMIT_PER_GUEST, config.CHAT_LIMIT_WINDOW_SECONDS),
        SlidingWindowLimiter(config.CHAT_LIMIT_PER_IP, config.CHAT_LIMIT_WINDOW_SECONDS),
    )


chat_limits = build_chat_limits()  # tests replace it


def client_ip(request: Request) -> str:
    """The caller's IP behind Railway's edge proxy: it appends the address it saw as the rightmost X-Forwarded-For
    entry. Entries to its left come from the client and can be forged, so they are never used."""
    forwarded = request.headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def limit_chat(request: Request, guest_id: Annotated[uuid.UUID | None, Depends(get_guest_id)]) -> None:
    """Public demo: cap chat turns (each one an LLM call) per guest and per IP. Off outside the demo."""
    if not config.DEMO_MODE:
        return
    by_guest, by_ip = chat_limits
    wait = admit([(by_guest, f"guest:{guest_id}"), (by_ip, f"ip:{client_ip(request)}")])
    if wait > 0:
        raise RateLimited(math.ceil(wait))


def take_turn_slot() -> Iterator[Slot]:
    """Must be the first dependency of the chat route, because get_guest_id already writes (touch_guest) while
    dependencies resolve, and a refused turn must write nothing and use none of the guest's rate-limit allowance.
    Releases only when an exception passes through it (a later dependency or the route failed before a response
    existed). Once a response exists, the response owns the slot. This relies only on exceptions reaching a yield
    dependency, which every FastAPI version does, and not on when its normal exit runs (that differs between 0.115 and
    0.143)."""
    limit = config.CHAT_MAX_IN_FLIGHT
    try:
        slot = admission.admit(limit)
    except admission.Busy:
        logger.warning("chat_busy in_flight=%d limit=%d", admission.in_flight(), limit)
        raise AssistantBusy(admission.retry_after_seconds(config.CHAT_BUSY_RETRY_SECONDS))
    try:
        yield slot
    except BaseException:
        slot.release()
        raise
