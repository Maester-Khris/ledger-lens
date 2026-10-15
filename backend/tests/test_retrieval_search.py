from app import config
from app.documents import dao as documents_dao
from app.documents.redact import PiiSpan, apply_redaction
from app.retrieval.index import index_version
from app.retrieval.search import search
from app.retrieval.vector_index import InMemoryVectorIndex, VectorRecord, vector_id
from tests.fakes import RecordingEmbeddings
from tests.test_retrieval_index import FIXTURE, parsed_version


def _indexed(db_session, tenant_id, texts):
    embeddings, index = RecordingEmbeddings(), InMemoryVectorIndex()
    version = parsed_version(db_session, tenant_id, texts=texts)
    index_version(db_session, version.id, embeddings=embeddings, vector_index=index)
    return version, embeddings, index


def test_full_text_finds_exact_terms_and_returns_citable_evidence(db_session, tenant_id):
    version, embeddings, index = _indexed(db_session, tenant_id, ("Fees are billed quarterly in arrears.", "Governed by Ontario law."))
    [first, *_] = search(db_session, tenant_id=tenant_id, query="quarterly arrears", embeddings=embeddings, vector_index=index)
    assert first.text == "Fees are billed quarterly in arrears."
    assert (first.version, first.page_start, first.section_path) == (1, 1, ("3. Fees",))
    assert "Governed by Ontario law." in first.context  # parent expansion: the whole section


def test_gate_refuses_when_nothing_is_relevant(db_session, tenant_id):
    _, embeddings, _ = _indexed(db_session, tenant_id, ("Fees are billed quarterly.",))
    empty_index = InMemoryVectorIndex()  # no dense candidates either
    assert search(db_session, tenant_id=tenant_id, query="charitable donations", embeddings=embeddings, vector_index=empty_index) == []


def test_stale_vector_is_dropped(db_session, tenant_id):
    version, embeddings, index = _indexed(db_session, tenant_id, ("Fees are billed quarterly.",))
    stale = vector_id(version.id, 99)  # a vector with no row in element_search
    index.upsert(str(tenant_id), [VectorRecord(stale, embeddings.embed_query("anything"), {"document_id": "x"})])
    ids = [e.element_id for e in search(db_session, tenant_id=tenant_id, query="anything", embeddings=embeddings, vector_index=index)]
    assert all(str(i) != stale for i in ids)


def test_query_tokenises_known_values(db_session, tenant_id):
    redaction = apply_redaction("Marie Tremblay", [PiiSpan(0, 14, "PERSON", 0.9)], tenant_id, config.PII_HMAC_KEY)
    documents_dao.save_tokens(db_session, tenant_id, redaction.tokens, config.PII_VAULT_KEY)
    db_session.commit()
    tokenised = documents_dao.tokenize_known_values(db_session, tenant_id, "What does marie  tremblay pay?", config.PII_HMAC_KEY, config.PII_VAULT_KEY)
    assert tokenised == f"What does {redaction.text} pay?"
    assert documents_dao.tokenize_known_values(db_session, tenant_id, "What does Luc pay?", config.PII_HMAC_KEY, config.PII_VAULT_KEY) == "What does Luc pay?"


def _scores(index, tenant_id, embeddings, query):
    return sorted((m.score for m in index.query(str(tenant_id), embeddings.embed_query(query), 10, None)), reverse=True)


def test_a_keyword_match_alone_does_not_open_the_gate(db_session, tenant_id, monkeypatch):
    _, embeddings, index = _indexed(db_session, tenant_id, ("Fees are billed quarterly in arrears.",))
    query = "fee quarterly"  # both words match the clause: a full-text hit
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", _scores(index, tenant_id, embeddings, query)[0] + 0.01)
    assert search(db_session, tenant_id=tenant_id, query=query, embeddings=embeddings, vector_index=index) == []


def test_passages_below_the_floor_never_reach_the_context(db_session, tenant_id, monkeypatch):
    _, embeddings, index = _indexed(db_session, tenant_id, ("Fees are billed quarterly in arrears.", "Governed by Ontario law."))
    query = "zzqx unmatched words"  # no full-text hit: only dense scores decide
    top, second = _scores(index, tenant_id, embeddings, query)[:2]
    assert top > second
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", (top + second) / 2)
    found = search(db_session, tenant_id=tenant_id, query=query, embeddings=embeddings, vector_index=index)
    assert len(found) == 1  # the weaker passage was dropped before fusion


def _terse_and_full(index, tenant_id, embeddings):
    """Two queries for one passage, the weaker one standing in for the model's terse rewrite, and a floor between them."""
    scored = sorted((_scores(index, tenant_id, embeddings, q)[0], q) for q in ("fees", "What are the fees calculated on?"))
    (low, terse), (high, full) = scored
    assert low < high
    return terse, full, (low + high) / 2


def test_a_passage_relevant_to_the_guests_question_survives_a_terse_model_query(db_session, tenant_id, monkeypatch):
    _, embeddings, index = _indexed(db_session, tenant_id, ("Fees are calculated on average daily net assets.",))
    terse, full, floor = _terse_and_full(index, tenant_id, embeddings)
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", floor)
    assert search(db_session, tenant_id=tenant_id, query=terse, embeddings=embeddings, vector_index=index) == []
    [found] = search(db_session, tenant_id=tenant_id, query=terse, question=full, embeddings=embeddings, vector_index=index)
    assert found.text == "Fees are calculated on average daily net assets."


def test_a_question_below_the_floor_opens_nothing(db_session, tenant_id, monkeypatch):
    _, embeddings, index = _indexed(db_session, tenant_id, ("Fees are calculated on average daily net assets.",))
    terse, _, floor = _terse_and_full(index, tenant_id, embeddings)
    monkeypatch.setattr(config, "MIN_DENSE_SIMILARITY", floor)
    assert search(db_session, tenant_id=tenant_id, query=terse, question=terse, embeddings=embeddings, vector_index=index) == []
