import uuid

import pytest

from app import config
from app.documents import dao, vault
from app.documents.redact import PiiDetector, PiiSpan, TOKEN_PATTERN, apply_redaction, make_token

KEY = "k" * 32
TENANT = uuid.UUID("00000000-0000-0000-0000-00000000000a")


def test_same_value_same_token_across_calls():
    a = make_token(TENANT, "PERSON", "Marie  Tremblay", KEY)
    b = make_token(TENANT, "PERSON", "marie tremblay", KEY)  # whitespace and case normalised
    assert a == b
    assert TOKEN_PATTERN.fullmatch(a)


def test_token_depends_on_tenant_type_and_key():
    base = make_token(TENANT, "PERSON", "Marie Tremblay", KEY)
    assert make_token(uuid.uuid4(), "PERSON", "Marie Tremblay", KEY) != base
    assert make_token(TENANT, "EMAIL_ADDRESS", "Marie Tremblay", KEY) != base
    assert make_token(TENANT, "PERSON", "Marie Tremblay", "x" * 32) != base


def test_apply_redaction_replaces_spans_and_collects_values():
    text = "Client Marie Tremblay, SIN 130 692 544."
    spans = [PiiSpan(7, 21, "PERSON", 0.85), PiiSpan(27, 38, "CA_SIN", 1.0)]
    result = apply_redaction(text, spans, TENANT, KEY)
    assert "Marie" not in result.text and "130 692 544" not in result.text
    assert result.text.startswith("Client <PERSON_") and result.text.endswith(">.")
    assert sorted(v[1] for v in result.tokens.values()) == ["130 692 544", "Marie Tremblay"]


def test_overlapping_spans_keep_the_longest():
    text = "Call 514-555-0142 now"
    spans = [PiiSpan(5, 17, "PHONE_NUMBER", 0.7), PiiSpan(9, 17, "US_BANK_NUMBER", 0.4)]
    result = apply_redaction(text, spans, TENANT, KEY)
    assert result.text.count("<") == 1
    assert list(result.tokens.values()) == [("PHONE_NUMBER", "514-555-0142")]


def test_vault_round_trip():
    blob = vault.encrypt_value("130 692 544", config.PII_VAULT_KEY)
    assert b"130" not in blob
    assert vault.decrypt_value(blob, config.PII_VAULT_KEY) == "130 692 544"


def test_reveal_replaces_known_tokens(db_session, tenant_id):
    redaction = apply_redaction("Client Marie Tremblay", [PiiSpan(7, 21, "PERSON", 0.9)], tenant_id, config.PII_HMAC_KEY)
    dao.save_tokens(db_session, tenant_id, redaction.tokens, config.PII_VAULT_KEY)
    dao.save_tokens(db_session, tenant_id, redaction.tokens, config.PII_VAULT_KEY)  # second save is a no-op
    db_session.commit()
    assert dao.reveal(db_session, tenant_id, [redaction.text, "no tokens"], config.PII_VAULT_KEY) == [
        "Client Marie Tremblay", "no tokens",
    ]


@pytest.mark.slow
def test_presidio_finds_name_sin_email_and_phone():
    text = ("Primary client: Marie Tremblay, Social Insurance Number 130 692 544. "
            "Email: marie.tremblay@example.com. Telephone: 514-555-0142.")
    found = {span.entity_type for span in PiiDetector().detect(text)}
    assert {"PERSON", "CA_SIN", "EMAIL_ADDRESS", "PHONE_NUMBER"} <= found


@pytest.mark.slow
def test_presidio_finds_address_and_postal_code():
    text = "Home address: 123 Main Street Unit 4B, Toronto, Province of Ontario, M5V 2T6, Canada."
    spans = PiiDetector().detect(text)
    found = {span.entity_type for span in spans}
    assert "STREET_ADDRESS" in found
    assert "POSTAL_CODE" in found
    # Province of Ontario and Toronto should not be tokenised as LOCATION
    assert "LOCATION" not in found


@pytest.mark.slow
def test_presidio_leaves_governing_law_and_dates_alone():
    text = "This Agreement shall be governed by the laws of the Province of Ontario, effective January 1, 2026."
    assert PiiDetector().detect(text) == []


@pytest.mark.slow
def test_detector_loads_the_medium_spacy_model():
    # md, not presidio's default lg: same NER accuracy for names, ~5x less RAM next to Docling in the worker
    nlp = PiiDetector()._engine.nlp_engine.nlp["en"]
    assert nlp.meta["name"] == "core_web_md"

def test_shared_regexes_do_not_tokenise_amounts():
    from app.documents.redact import REGEX_RECOGNIZERS
    
    cases = ["50000", "$100 000 000", "$1,250,000", "25 basis points by way of fee",
             "File No. 811-02729", "CIK 0000052136", "0.25% on the first $500,000", "within 30 days",
             "fee up to 50000 of assets", "Fees on 25000 dollars", "at 12345 Main", "046 454 287", "012 345 678"]
    
    for text in cases:
        for entity_type, (pattern, validator) in REGEX_RECOGNIZERS.items():
            for match in pattern.finditer(text):
                if validator is None or validator(match.group(0)):
                    pytest.fail(f"'{text}' falsely matched {entity_type} ({match.group(0)})")

def test_shared_regexes_tokenise_true_pii():
    from app.documents.redact import REGEX_RECOGNIZERS
    
    cases = {
        "M5V 2T6": "POSTAL_CODE",
        "Philadelphia, PA 19103": "POSTAL_CODE",
        "123 Main Street Unit 4B": "STREET_ADDRESS",
        "2020 Calamos Court": "STREET_ADDRESS",
        "046 454 286": "CA_SIN",
        "SIN 046454286": "CA_SIN",
        "(416) 555-0199": "PHONE_NUMBER",
        "+1 416-555-0199": "PHONE_NUMBER",
        "4111 1111 1111 1111": "CREDIT_CARD",
    }
    
    for text, expected_entity in cases.items():
        found = False
        for entity_type, (pattern, validator) in REGEX_RECOGNIZERS.items():
            for match in pattern.finditer(text):
                if validator is None or validator(match.group(0)):
                    if entity_type == expected_entity:
                        found = True
        assert found, f"Failed to match {expected_entity} in '{text}'"

@pytest.mark.slow
def test_presidio_finds_us_bank_number(monkeypatch):
    import app.documents.redact
    monkeypatch.setattr(app.documents.redact, "MIN_PII_SCORE", 0.4)
    text = "Account number: 123456789012"
    spans = PiiDetector().detect(text)
    assert any(s.entity_type == "US_BANK_NUMBER" for s in spans)
