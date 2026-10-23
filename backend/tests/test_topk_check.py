import uuid
from types import SimpleNamespace

from scripts import topk_check

DOC_A, DOC_B = uuid.uuid4(), uuid.uuid4()
KEYS = {DOC_A: "tremblay-ima", DOC_B: "other"}


def _hit(document_id, page):
    return SimpleNamespace(document_id=document_id, page_start=page)


def test_rank_is_the_first_hit_on_the_expected_document_and_page():
    hits = [_hit(DOC_B, 1), _hit(DOC_A, 2), _hit(DOC_A, 3)]
    assert topk_check.rank_of_expected(hits, {"expect_document": "tremblay-ima", "expect_page": 3}, KEYS) == 3
    assert topk_check.rank_of_expected(hits, {"expect_document": "tremblay-ima", "expect_page": None}, KEYS) == 2
    assert topk_check.rank_of_expected(hits, {"expect_document": "tremblay-ima", "expect_page": 9}, KEYS) is None


def test_the_search_tool_takes_its_hit_count_from_config(monkeypatch):
    from app import config
    from app.assistant import tools
    seen = {}
    monkeypatch.setattr(config, "SEARCH_TOP_K", 5)
    monkeypatch.setattr(tools, "search", lambda *args, **kwargs: seen.update(kwargs) or [])
    ctx = SimpleNamespace(session=None, tenant_id=DOC_A, embeddings=None, vector_index=None, document_id=None, question=None)
    tools._search_contracts(ctx, tools.SearchArgs(query="fees"))
    assert seen["k"] == 5


def test_the_eval_config_hash_changes_with_the_hit_count(monkeypatch):
    from app import config
    from app.assistant.graph import eval_config_hash
    monkeypatch.setattr(config, "SEARCH_TOP_K", 8)
    eight = eval_config_hash()
    monkeypatch.setattr(config, "SEARCH_TOP_K", 5)
    assert eval_config_hash() != eight
