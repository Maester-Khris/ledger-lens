"""Removes user text from Sentry events before they leave the process (spec P6, section 1).

The dashboard scrubber is a second layer; this runs first and is the one that is tested."""
from typing import Any

FILTERED = "[Filtered]"


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("query_string", None)
        request.pop("cookies", None)
    if "message" in event:
        event["message"] = FILTERED
    for exc in (event.get("exception") or {}).get("values", []):
        if "value" in exc:
            exc["value"] = FILTERED
    return event
