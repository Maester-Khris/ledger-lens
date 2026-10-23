from app import config
from app.documents import dao as documents_dao
from tests.support import record_statements

QUESTION = "What does Marie Tremblay pay under the agreement she signed in Toronto last spring with her advisor?"


def _tokenise(db_session, tenant_id, text):
    return documents_dao.tokenize_known_values(db_session, tenant_id, text, config.PII_HMAC_KEY, config.PII_VAULT_KEY)


def test_the_vault_lookup_sends_one_array_parameter(db_session, tenant_id):
    _, statements = record_statements(db_session, lambda: _tokenise(db_session, tenant_id, QUESTION))
    [(statement, parameters)] = [(s, p) for s, p in statements if "pii_tokens" in s]
    assert len(parameters) == 2  # tenant id and one array of candidate tokens, not one bind per candidate


def test_an_empty_or_blank_question_tokenises_to_itself(db_session, tenant_id):
    # Review Focus 1
    assert _tokenise(db_session, tenant_id, "") == ""
    assert _tokenise(db_session, tenant_id, "   ") == "   "
