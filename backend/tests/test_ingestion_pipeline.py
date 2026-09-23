from dataclasses import dataclass

from app.documents.types import VersionStage
from app.ingestion_pipeline import PARSE_REDACT, VersionStatus, next_stage, version_status


@dataclass(frozen=True)
class EventStub:
    stage: VersionStage
    detail: dict


def test_next_stage_returns_none_when_already_reached():
    events = [EventStub(VersionStage.stored, {}), EventStub(VersionStage.parsed, {})]
    assert next_stage([PARSE_REDACT], events) is None


def test_next_stage_returns_stage_when_prerequisite_met():
    events = [EventStub(VersionStage.stored, {})]
    assert next_stage([PARSE_REDACT], events) == PARSE_REDACT


def test_next_stage_returns_none_when_prerequisite_missing():
    assert next_stage([PARSE_REDACT], []) is None


def test_next_stage_stops_after_max_attempts():
    events = [EventStub(VersionStage.stored, {})] + [
        EventStub(VersionStage.failed, {"stage": "parse_redact"}) for _ in range(3)
    ]
    assert next_stage([PARSE_REDACT], events) is None


def test_version_status_infers_state_from_event_log():
    stored = [EventStub(VersionStage.stored, {})]
    assert version_status([PARSE_REDACT], stored) == VersionStatus("processing", "waiting for parse_redact")

    parsed = stored + [EventStub(VersionStage.parsed, {})]
    assert version_status([PARSE_REDACT], parsed) == VersionStatus("ready", None)

    failed = stored + [
        EventStub(VersionStage.failed, {"stage": "parse_redact", "error_type": "ValueError", "message": "bad doc"})
    ] * 3
    assert version_status([PARSE_REDACT], failed) == VersionStatus("failed", "parse_redact failed: ValueError bad doc")
