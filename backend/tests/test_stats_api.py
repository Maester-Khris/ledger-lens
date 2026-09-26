import json

import pytest

from app.assistant.models import ChatOutcome, ChatTurn
from app.reporting import dashboard
from tests.test_retrieval_index import parsed_version
from tests.test_reviews_api import _decide, _run


@pytest.fixture(autouse=True)
def fresh_stats_cache():
    dashboard._cache.clear()
    yield
    dashboard._cache.clear()


def _turn(tenant_id, latency_ms):
    return ChatTurn(tenant_id=tenant_id, session_id="s", question_redacted="q", answer_redacted="a", citations=[],
                    retrieved=[], outcome=ChatOutcome.answered, model_id="m", prompt_version="p", graph_version="g",
                    input_tokens=0, output_tokens=0, latency_ms=latency_ms)


def test_stats_count_documents_and_answer_latency(client, db_session, tenant_id):
    parsed_version(db_session, tenant_id)
    db_session.add_all([_turn(tenant_id, ms) for ms in (100, 200, 300, 400, 1000)])
    db_session.commit()
    response = client.get("/stats")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-cache"
    body = response.json()
    assert body["documents"]["total"] == 1 and body["documents"]["indexed_chunks"] == 0
    assert body["chat"] == {"turns_7d": 5, "latency_p50_ms": 300, "latency_p95_ms": 880}
    assert body["confidence_drop_rate"] is None
    assert body["last_ingestion_at"] is not None


def test_unchanged_stats_revalidate_with_304(client):
    first = client.get("/stats")
    again = client.get("/stats", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_writes_invalidate_the_cached_stats(client, db_session, tenant_id):
    _, run = _run(db_session, tenant_id)
    assert client.get("/stats").json()["reviews_pending"] == 2
    assert _decide(client, run, "fee_method", "confirmed").status_code == 201
    assert client.get("/stats").json()["reviews_pending"] == 1


def test_stats_are_cached_for_the_ttl(db_session, tenant_id):
    now = [100.0]
    first = dashboard.cached_dashboard_stats(db_session, tenant_id, clock=lambda: now[0])
    parsed_version(db_session, tenant_id)
    assert dashboard.cached_dashboard_stats(db_session, tenant_id, clock=lambda: now[0]).documents_total == first.documents_total
    now[0] += dashboard.STATS_TTL_SECONDS
    assert dashboard.cached_dashboard_stats(db_session, tenant_id, clock=lambda: now[0]).documents_total == first.documents_total + 1


def test_eval_summary_reads_only_the_report_for_the_running_config(tmp_path):
    (tmp_path / "eval-abc123.json").write_text(json.dumps({
        "config_hash": "abc123", "chat_model": "gpt-x",
        "metrics": {"numbers_ok": 1.0, "refusal_ok": 0.875, "citation_hit": 0.875}, "results": [{}] * 8,
    }))
    summary = dashboard.eval_summary(tmp_path, "abc123")
    assert (summary.cases, summary.numbers_ok, summary.refusal_ok, summary.citation_hit) == (8, 1.0, 0.875, 0.875)
    assert dashboard.eval_summary(tmp_path, "other") is None


def test_config_is_cacheable_and_revalidates(client):
    response = client.get("/config")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=3600"
    body = response.json()
    assert body["embedding_model"] and body["embedding_dimensions"] > 0
    assert body["retrieval"]["search_candidates"] > 0
    again = client.get("/config", headers={"If-None-Match": response.headers["etag"]})
    assert again.status_code == 304
