"""A document's history as one ordered list: how a contract became ledger entries. Read-only."""
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.contracts import dao as contracts_dao
from app.documents import dao as documents_dao
from app.governance import dao as governance_dao
from app.ledger import dao as ledger_dao


@dataclass(frozen=True)
class TimelineItem:
    at: datetime
    kind: str  # ingested | extracted | reviewed | ai_proposed | decided | posted
    title: str
    detail: dict = field(default_factory=dict)
    links: dict = field(default_factory=dict)


def build_timeline(items: list[TimelineItem]) -> list[TimelineItem]:
    return sorted(items, key=lambda item: item.at)


def document_timeline(session: Session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> list[TimelineItem] | None:
    if documents_dao.find_document(session, tenant_id, document_id) is None:
        return None
    items = [
        TimelineItem(event.created_at, "ingested", f"v{version} · {event.stage.value}", {"stage": event.stage.value})
        for version, event in documents_dao.version_events_for_document(session, document_id)
    ]
    for run, reviews in contracts_dao.runs_with_reviews(session, document_id):
        accepted = contracts_dao.accepted_count(session, run.id)
        items.append(TimelineItem(run.created_at, "extracted", "Terms extracted", {"run_id": str(run.id), "accepted": accepted}))
        items += [TimelineItem(r.decided_at, "reviewed", f"{r.field_path} {r.decision.value}",
                               {"field_path": r.field_path, "decided_by": r.decided_by}) for r in reviews]
    for invocation, decision in governance_dao.invocations_for_document(session, tenant_id, document_id):
        items.append(TimelineItem(invocation.created_at, "ai_proposed", invocation.tool_name, {
            "document_id": str(document_id), "amount_minor": invocation.result_amount_minor,
            "currency": invocation.result_currency, "invocation_id": str(invocation.id)}))
        if decision is None:
            continue
        items.append(TimelineItem(decision.decided_at, "decided", f"{decision.decision.value} by {decision.decided_by}",
                                  {"reason": decision.reason}))
        if decision.posting_id is not None:
            posting = ledger_dao.get_posting(session, tenant_id=tenant_id, posting_id=decision.posting_id)
            labels = ledger_dao.account_labels(session, (e.account_id for e in posting.entries))
            items.append(TimelineItem(posting.created_at, "posted", posting.description or "Posting", {
                "posting_id": str(posting.id),
                "entries": [{"account": labels[e.account_id].name, "direction": e.direction.value, "amount_minor": e.amount,
                             "currency": labels[e.account_id].currency} for e in posting.entries],
            }, {"ledger": f"/ledger?posting={posting.id}"}))
    return build_timeline(items)
