from datetime import date, timedelta

from sqlalchemy.dialects.postgresql import Range


def date_range(valid_from: date, valid_until: date | None) -> Range[date]:
    """Inclusive [from, until]; open-ended when until is None. Postgres stores it as [from, until+1)."""
    if valid_until is None:
        return Range(valid_from, None, bounds="[)")
    return Range(valid_from, valid_until, bounds="[]")


def range_end_inclusive(value: Range[date]) -> date | None:
    if value.upper is None:
        return None
    return value.upper if value.bounds[1] == "]" else value.upper - timedelta(days=1)