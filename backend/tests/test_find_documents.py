import json
import uuid

from app import config
from app.assistant.tools import FindArgs, ToolContext, default_tools
from app.documents import dao as documents_dao
from app.documents.sniff import PdfFacts
from app.governance.dao import ModelConfig
from app.retrieval.vector_index import InMemoryVectorIndex
from tests.fakes import RecordingEmbeddings
from tests.support import make_tenant, record_statements
from tests.test_retrieval_index import FIXTURE

FIND_TOOL = next(spec for spec in default_tools() if spec.name == "find_documents")
NOMURA = ("nomura-tax-free-colorado-ima", "Voyageur Mutual Funds II / Delaware Management — IMA (2025)")
CALAMOS = ("edgar-calamos-investment-trust-ex-99-d", "Calamos Investment Trust — EX-99.D (2021-03-01)")
TREMBLAY = ("tremblay-household-ima", "Tremblay household — Investment Management Agreement (synthetic)")


def _document(db_session, tenant_id, key, title) -> uuid.UUID:
    data = FIXTURE.read_bytes()
    return documents_dao.register_upload(
        db_session, tenant_id=tenant_id, document_key=key, title=title, source_url=None, data=data,
        facts=PdfFacts(2, len(data)), uploaded_by="test", store_root=config.DOCUMENT_STORE_DIR,
    ).document.id


def _corpus(db_session, tenant_id) -> dict[str, uuid.UUID]:
    return {key: _document(db_session, tenant_id, key, title) for key, title in (NOMURA, CALAMOS, TREMBLAY)}


def _find(db_session, tenant_id, name, document_id=None):
    return documents_dao.find_documents(db_session, tenant_id, name, document_id)


def _ctx(db_session, tenant_id, document_id=None):
    return ToolContext(session=db_session, tenant_id=tenant_id, session_id="find", turn_id=uuid.uuid4(),
                       embeddings=RecordingEmbeddings(), vector_index=InMemoryVectorIndex(),
                       model=ModelConfig("fake", "scripted", "p", 0), hmac_key=config.PII_HMAC_KEY,
                       vault_key=config.PII_VAULT_KEY, document_id=document_id)


def test_a_name_found_in_the_title_comes_first(db_session, tenant_id):
    ids = _corpus(db_session, tenant_id)
    assert _find(db_session, tenant_id, "the Calamos fund")[0].id == ids[CALAMOS[0]]


def test_a_name_found_only_in_the_document_key_is_found(db_session, tenant_id):
    # Gate 1 (batch-a-r1): this contract is named only in its key, not in its title.
    ids = _corpus(db_session, tenant_id)
    assert _find(db_session, tenant_id, "Nomura Tax-Free Colorado Fund")[0].id == ids[NOMURA[0]]


def test_one_word_of_the_name_is_enough_and_case_does_not_matter(db_session, tenant_id):
    ids = _corpus(db_session, tenant_id)
    assert _find(db_session, tenant_id, "TREMBLAY")[0].id == ids[TREMBLAY[0]]


def test_no_match_gives_an_empty_list(db_session, tenant_id):
    _corpus(db_session, tenant_id)
    assert _find(db_session, tenant_id, "zebra quartz") == []


def test_a_blank_or_punctuation_only_name_gives_an_empty_list(db_session, tenant_id):
    _corpus(db_session, tenant_id)
    for name in ("", "   ", "the", "&|!:*()'\"<>"):
        assert _find(db_session, tenant_id, name) == [], name


def test_punctuation_in_a_name_does_not_break_the_query(db_session, tenant_id):
    ids = _corpus(db_session, tenant_id)
    assert _find(db_session, tenant_id, "Calamos: 'Investment' & Trust | (2021) <x>!")[0].id == ids[CALAMOS[0]]


def test_an_accented_name_is_matched_whole(db_session, tenant_id):
    expected = _document(db_session, tenant_id, "cote-family-ima", "Côté family — IMA")
    _document(db_session, tenant_id, "edgar-t-rowe-price-ex-99-d", "T. Rowe Price — EX-99.D")
    assert [t.id for t in _find(db_session, tenant_id, "the Côté family")] == [expected]


def test_at_most_five_matches(db_session, tenant_id):
    for n in range(7):
        _document(db_session, tenant_id, f"acme-fund-{n}", f"Acme Fund {n}")
    assert len(_find(db_session, tenant_id, "Acme")) == 5


def test_other_tenants_and_other_scopes_are_not_found(db_session, tenant_id):
    ids = _corpus(db_session, tenant_id)
    assert _find(db_session, make_tenant(db_session), "Calamos") == []
    assert _find(db_session, tenant_id, "Calamos", document_id=ids[NOMURA[0]]) == []
    assert [t.id for t in _find(db_session, tenant_id, "Nomura", document_id=ids[NOMURA[0]])] == [ids[NOMURA[0]]]


def test_the_search_is_one_statement(db_session, tenant_id):
    _corpus(db_session, tenant_id)
    _, statements = record_statements(db_session, lambda: _find(db_session, tenant_id, "Calamos Investment Trust"))
    assert len(statements) == 1


def test_the_tool_returns_matches_with_id_key_and_title(db_session, tenant_id):
    ids = _corpus(db_session, tenant_id)
    body = json.loads(FIND_TOOL.run(_ctx(db_session, tenant_id), FindArgs(name="Calamos")).content)
    assert body["matches"][0] == {"document_id": str(ids[CALAMOS[0]]), "document_key": CALAMOS[0], "title": CALAMOS[1]}
    assert "hint" not in body


def test_the_tool_says_what_to_do_when_nothing_matches(db_session, tenant_id):
    _corpus(db_session, tenant_id)
    body = json.loads(FIND_TOOL.run(_ctx(db_session, tenant_id), FindArgs(name="zebra quartz")).content)
    assert body["matches"] == [] and "search_contracts" in body["hint"]
