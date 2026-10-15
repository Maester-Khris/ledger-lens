"""The 24-hour purge of demo guests' overlay decisions (spec P2+P9, D4).

Timing only reclaims storage: overlay rows are invisible to every other guest whenever they are deleted.
It runs when a new guest arrives, so there is no scheduler to deploy or watch."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.assistant import dao as assistant_dao
from app.contracts import dao as contracts_dao
from app.governance import dao as governance_dao

OVERLAY_TTL = timedelta(hours=24)


def purge_stale_overlays(session: Session, tenant_id: uuid.UUID, now: datetime) -> None:
    stale = assistant_dao.stale_guest_ids(session, tenant_id, before=now - OVERLAY_TTL)
    if stale:
        contracts_dao.purge_guest_reviews(session, stale)
        governance_dao.purge_guest_decisions(session, stale)
        session.commit()
