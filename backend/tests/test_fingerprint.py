import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.ledger.fingerprint import canonical_json, posting_fingerprint

A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
B = uuid.UUID("00000000-0000-0000-0000-00000000000b")


def _fp(entries, *, effective_at=None, description="Fee"):
    return posting_fingerprint(
        description=description,
        effective_at=effective_at,
        source="api",
        reverses_posting_id=None,
        entries=entries,
    )


def test_canonical_json_sorts_keys_and_strips_whitespace():
    assert canonical_json({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_fingerprint_ignores_entry_order():
    assert _fp([(A, "debit", 100), (B, "credit", 100)]) == _fp([(B, "credit", 100), (A, "debit", 100)])


def test_fingerprint_changes_when_an_amount_changes():
    assert _fp([(A, "debit", 100), (B, "credit", 100)]) != _fp([(A, "debit", 101), (B, "credit", 101)])


def test_fingerprint_treats_equal_instants_in_different_offsets_as_equal():
    utc = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
    toronto = datetime(2026, 9, 29, 20, 0, tzinfo=timezone(timedelta(hours=-4)))
    entries = [(A, "debit", 1), (B, "credit", 1)]
    assert _fp(entries, effective_at=utc) == _fp(entries, effective_at=toronto)


def test_fingerprint_rejects_naive_timestamps():
    with pytest.raises(ValueError):
        _fp([(A, "debit", 1), (B, "credit", 1)], effective_at=datetime(2026, 9, 30))


def test_fingerprint_is_64_lowercase_hex():
    value = _fp([(A, "debit", 1), (B, "credit", 1)])
    assert len(value) == 64 and value == value.lower()
