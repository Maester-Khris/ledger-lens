import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone


def canonical_json(value: object) -> str:
    """Deterministic JSON: sorted keys, no whitespace.

    Equivalent to RFC 8785 (JCS) for payloads that contain no floats, which is
    guaranteed here because amounts are integer minor units.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("effective_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def posting_fingerprint(
    *,
    description: str | None,
    effective_at: datetime | None,
    source: str,
    reverses_posting_id: uuid.UUID | None,
    entries: Iterable[tuple[uuid.UUID, str, int]],
) -> str:
    """Hash of the business meaning of a posting request, used to tell a retry from a key reuse."""
    normalized_entries = sorted(
        (
            {"account_id": str(account_id), "direction": direction, "amount": amount}
            for account_id, direction, amount in entries
        ),
        key=lambda entry: (entry["account_id"], entry["direction"], entry["amount"]),
    )
    payload = {
        "description": description,
        "effective_at": _utc_iso(effective_at),
        "entries": normalized_entries,
        "reverses_posting_id": None if reverses_posting_id is None else str(reverses_posting_id),
        "source": source,
    }
    return sha256_hex(canonical_json(payload))
