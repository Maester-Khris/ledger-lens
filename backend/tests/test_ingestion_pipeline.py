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


def test_a_failed_stage_does_not_block_an_independent_one():
    from app.ingestion_pipeline import MAX_STAGE_ATTEMPTS, StageSpec
    index = StageSpec("index", VersionStage.parsed, VersionStage.indexed)
    extract = StageSpec("extract", VersionStage.parsed, VersionStage.extracted)
    events = [EventStub(VersionStage.stored, {}), EventStub(VersionStage.parsed, {})] + [
        EventStub(VersionStage.failed, {"stage": "index", "error_type": "Timeout", "message": ""})
    ] * MAX_STAGE_ATTEMPTS
    assert next_stage([PARSE_REDACT, index, extract], events) == extract


# --- Worker loop against the database: the lease, the failure record, the stage handoff ---

from pathlib import Path  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app import config  # noqa: E402
from app.documents import dao  # noqa: E402
from app.documents.sniff import PdfFacts  # noqa: E402
from app.ingestion_pipeline import run_pending  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "documents" / "client_agreement.pdf"


def _stored(db_session, tenant_id):
    data = FIXTURE.read_bytes()
    return dao.register_upload(
        db_session, tenant_id=tenant_id, document_key="tremblay-ima", title="IMA", source_url=None,
        data=data, facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).version


def test_run_pending_records_a_raising_stage_as_failed(session_factory, db_session, tenant_id):
    version = _stored(db_session, tenant_id)

    def boom(_session, version_id):
        if version_id == version.id:  # other tests' versions share the database; leave them alone
            raise ValueError("parser exploded")

    run_pending(session_factory, {"parse_redact": boom}, pipeline=(PARSE_REDACT,))
    last = dao.version_events(db_session, version.id)[-1]
    assert last.stage is VersionStage.failed
    assert last.detail == {"stage": "parse_redact", "error_type": "ValueError", "message": "parser exploded"}


def test_run_pending_runs_the_next_stage(session_factory, db_session, tenant_id):
    version = _stored(db_session, tenant_id)

    def fake_parse(session, version_id):
        if version_id == version.id:
            dao.append_event(session, version_id, VersionStage.parsed, {})
            session.commit()

    run_pending(session_factory, {"parse_redact": fake_parse}, pipeline=(PARSE_REDACT,))
    assert dao.version_events(db_session, version.id)[-1].stage is VersionStage.parsed


def test_run_pending_skips_a_version_another_worker_holds(session_factory, db_session, tenant_id):
    version = _stored(db_session, tenant_id)
    calls = []
    with session_factory.kw["bind"].connect() as other_worker:
        other_worker.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": str(version.id)})
        try:
            run_pending(session_factory, {"parse_redact": lambda _s, vid: calls.append(vid)}, pipeline=(PARSE_REDACT,))
        finally:
            other_worker.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": str(version.id)})
    assert version.id not in calls
    assert [e.stage for e in dao.version_events(db_session, version.id)] == [VersionStage.stored]
