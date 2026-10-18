"""X1 layer 2 (spec section 6): a vision model reads redacted crops of class A fields, never seeing the extracted value.
Disagreement, failure or malformed output routes to review; `client` never reaches the model."""
import base64
import io
import json
import re
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from PIL import Image
from pydantic import Field
from sqlalchemy import select

from app import config
from app.contracts import dao as contracts_dao
from app.contracts.crops import ocr_lines
from app.contracts.models import FieldVerification
from app.contracts.verify import VisionVerifier, run_verification
from app.documents import dao as documents_dao
from app.documents.types import VersionStage
from scripts.load import mock_openai
from tests.test_contracts_verify import TABLE, TRUE_VALUES, fixture_run, keys
from tests.test_image_pii_egress import RAW_PII

TRUE_READINGS = {**TRUE_VALUES, "fee_tiers": [{"band_text": b["band_text"], "rate_text": b["rate_text"]} for b in TABLE]}
CLASS_A = {"fee_tiers", "fee_basis", "fee_method", "currency", "billing_frequency", "payment_timing"}


def _text_parts(messages: list[BaseMessage]) -> str:
    """Everything the model reads as text (images excluded)."""
    parts = []
    for message in messages:
        content = message.content
        if isinstance(content, str):
            parts.append(content)
        else:
            parts += [p["text"] for p in content if isinstance(p, dict) and p.get("type") == "text"]
    return "\n".join(parts)


class FakeVision(BaseChatModel):
    """Answers each structured request from `answers[field_path]`, found by the `field: <path>` line the verifier
    puts in its text. An answer is the schema's dict, "malformed" (unparseable output) or an exception to raise."""

    answers: dict[str, Any] = Field(default_factory=dict)
    seen: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake-vision"

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        raise AssertionError("the verifier must use structured output")

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any):
        assert include_raw, "the verifier needs the raw message for token usage"

        def run(messages: list[BaseMessage]) -> dict:
            self.seen.append(messages)
            path = re.search(r"field: (\S+)", _text_parts(messages)).group(1)
            answer = self.answers[path]
            if isinstance(answer, Exception):
                raise answer
            if answer == "malformed":
                return {"raw": AIMessage(content="{"), "parsed": None, "parsing_error": ValueError("not JSON")}
            usage = {"input_tokens": 1000, "output_tokens": 20, "total_tokens": 1020}
            return {"raw": AIMessage(content="", usage_metadata=usage), "parsed": schema.model_validate(answer),
                    "parsing_error": None}

        return RunnableLambda(run)


def _answers(**overrides: Any) -> dict[str, Any]:
    return {path: {"value": value} for path, value in TRUE_READINGS.items()} | overrides


def _rows(db_session, run_id) -> dict[tuple[str, str], FieldVerification]:
    rows = db_session.scalars(select(FieldVerification).where(FieldVerification.run_id == run_id))
    return {(r.field_path, r.layer): r for r in rows}


def _verify(db_session, version_id, model: BaseChatModel) -> None:
    run_verification(db_session, version_id, store_root=config.DOCUMENT_STORE_DIR, **keys(),
                     vision=VisionVerifier(model, "gpt-6-luna"))


@pytest.mark.slow
def test_vision_agreement_serves_class_a_and_client_never_goes_to_vision(db_session, tenant_id):
    version, run = fixture_run(db_session, tenant_id, "x1-vision-agree")
    model = FakeVision(answers=_answers())
    _verify(db_session, version.id, model)

    rows = _rows(db_session, run.id)
    vision_paths = {path for path, layer in rows if layer == "vision"}
    assert CLASS_A <= vision_paths and "client" not in vision_paths
    assert all(rows[(p, "vision")].outcome == "agree" for p in CLASS_A)
    assert rows[("fee_method", "vision")].verifier == "gpt-6-luna"
    assert rows[("currency", "vision")].cost_usd == Decimal("0.000110")  # 1000 in, 20 out at $0.10 / $0.50 per 1M
    asked = [re.search(r"field: (\S+)", _text_parts(m)).group(1) for m in model.seen]
    assert "client" not in asked

    served = contracts_dao.served_fields(db_session, tenant_id, version.document_id)
    assert {"fee_tiers[0]", "fee_tiers[2]", "fee_method", "currency", "billing_frequency", "payment_timing",
            "fee_basis"} <= set(served.fields)
    event = documents_dao.version_events(db_session, version.id)[-1]
    assert event.stage is VersionStage.verified and event.detail["cost_usd"] > 0


@pytest.mark.slow
def test_vision_prompt_never_contains_the_extracted_value(db_session, tenant_id):
    version, _run = fixture_run(db_session, tenant_id, "x1-vision-anchor")
    model = FakeVision(answers=_answers())
    _verify(db_session, version.id, model)
    text = "\n".join(_text_parts(m) for m in model.seen)
    for value in ("1.00%", "0.85%", "0.65%", "$1,500,000", "combined household market value", "Maple Ridge"):
        assert value not in text, value  # no anchoring: the model reads the image, not our answer


@pytest.mark.slow
def test_vision_malformed_or_failed_output_records_error(db_session, tenant_id):
    version, run = fixture_run(db_session, tenant_id, "x1-vision-error")
    model = FakeVision(answers=_answers(fee_method="malformed", currency=TimeoutError("provider timed out"),
                                        payment_timing={"value": "advance"}))
    _verify(db_session, version.id, model)  # one bad call never blocks the document

    rows = _rows(db_session, run.id)
    assert rows[("fee_method", "vision")].outcome == "error"
    assert rows[("currency", "vision")].outcome == "error"
    assert rows[("payment_timing", "vision")].outcome == "disagree"
    assert rows[("billing_frequency", "vision")].outcome == "agree"
    served = contracts_dao.served_fields(db_session, tenant_id, version.document_id)
    assert {"fee_method", "currency", "payment_timing"} <= set(served.unserved)
    assert documents_dao.version_events(db_session, version.id)[-1].stage is VersionStage.verified


@pytest.mark.slow
def test_class_b_goes_to_vision_when_layer1_fails(db_session, tenant_id):
    version, run = fixture_run(db_session, tenant_id, "x1-vision-classb", values={"adviser": "Birch Hill Capital"})
    model = FakeVision(answers=_answers())
    _verify(db_session, version.id, model)
    rows = _rows(db_session, run.id)
    assert rows[("adviser", "ocr_local")].outcome != "agree"
    assert rows[("adviser", "vision")].outcome == "disagree"  # the model reads Maple Ridge, extraction said Birch Hill


def _images_in(body: dict) -> list[Image.Image]:
    images = []
    for message in body.get("messages", []):
        content = message.get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "image_url":
                data = part["image_url"]["url"].split(",", 1)[1]
                images.append(Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB"))
    return images


@pytest.mark.slow
def test_no_raw_pii_in_any_vision_request_body(db_session, tenant_id, monkeypatch):
    """The real ChatOpenAI client against the provider mock: decode every image actually sent, OCR it."""
    monkeypatch.setenv("MOCK_DELAY_SCALE", "0")
    bodies: list[dict] = []
    client = TestClient(mock_openai.app)
    client.event_hooks = {"request": [lambda request: bodies.append(json.loads(request.content))]}
    model = ChatOpenAI(model="gpt-6-luna", api_key="mock", base_url="http://testserver/v1", max_retries=0,
                       http_client=client)
    version, run = fixture_run(db_session, tenant_id, "x1-vision-egress")
    _verify(db_session, version.id, model)

    assert bodies, "the verifier sent nothing"
    for body in bodies:
        text = json.dumps(body, ensure_ascii=False)
        assert "field: client" not in text
        assert not any(value in text for value in RAW_PII)
        for image in _images_in(body):
            read = " ".join(line.text for line in ocr_lines(image))
            assert [value for value in RAW_PII if value in read] == []
    assert len([b for b in bodies if _images_in(b)]) >= len(CLASS_A)
