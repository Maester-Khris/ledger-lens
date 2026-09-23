import hashlib
import hmac
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

# Personal data only. Organisations, locations and dates stay readable: contracts need
# "Province of Ontario" and "January 1, 2026" as terms. Known gap: a street address is not tokenised.
PII_ENTITIES = (
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CA_SIN", "US_SSN", "CREDIT_CARD", "IBAN_CODE", "US_BANK_NUMBER",
)
MIN_PII_SCORE = 0.5
TOKEN_DIGEST_CHARS = 12
TOKEN_PATTERN = re.compile(r"<([A-Z_]+)_([0-9a-f]{12})>")


@dataclass(frozen=True)
class PiiSpan:
    start: int
    end: int
    entity_type: str
    score: float


@dataclass(frozen=True)
class Redaction:
    text: str
    tokens: dict[str, tuple[str, str]] = field(default_factory=dict)  # token -> (entity_type, original value)


def _normalise(value: str) -> str:
    return " ".join(value.split()).casefold()


def make_token(tenant_id: uuid.UUID, entity_type: str, value: str, key: str) -> str:
    """Deterministic per tenant: the same person gets the same token in every document and in queries."""
    message = f"{tenant_id}|{entity_type}|{_normalise(value)}".encode()
    digest = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:TOKEN_DIGEST_CHARS]
    return f"<{entity_type}_{digest}>"


def _non_overlapping(spans: Sequence[PiiSpan]) -> list[PiiSpan]:
    kept: list[PiiSpan] = []
    for span in sorted(spans, key=lambda s: (-(s.end - s.start), -s.score, s.start)):
        if all(span.end <= k.start or span.start >= k.end for k in kept):
            kept.append(span)
    return sorted(kept, key=lambda s: s.start)


def apply_redaction(text: str, spans: Sequence[PiiSpan], tenant_id: uuid.UUID, key: str) -> Redaction:
    tokens: dict[str, tuple[str, str]] = {}
    pieces: list[str] = []
    cursor = 0
    for span in _non_overlapping(spans):
        value = text[span.start:span.end]
        token = make_token(tenant_id, span.entity_type, value, key)
        tokens[token] = (span.entity_type, value)
        pieces.append(text[cursor:span.start])
        pieces.append(token)
        cursor = span.end
    pieces.append(text[cursor:])
    return Redaction("".join(pieces), tokens)


class PiiDetector:
    """Presidio analyzer with the Canadian SIN recognizer switched on (it ships disabled)."""

    def __init__(self) -> None:
        from presidio_analyzer import AnalyzerEngine

        self._engine = AnalyzerEngine()
        self._add_ca_sin()

    def _add_ca_sin(self) -> None:
        try:
            from presidio_analyzer.predefined_recognizers import CaSinRecognizer
        except ImportError:
            import importlib, pkgutil
            # Locate CaSinRecognizer in any submodule of presidio_analyzer
            import presidio_analyzer
            CaSinRecognizer = None
            for importer, modname, ispkg in pkgutil.walk_packages(
                path=presidio_analyzer.__path__, prefix=presidio_analyzer.__name__ + ".", onerror=lambda x: None
            ):
                mod = importlib.import_module(modname)
                if hasattr(mod, "CaSinRecognizer"):
                    CaSinRecognizer = getattr(mod, "CaSinRecognizer")
                    break
            if CaSinRecognizer is None:
                return  # not available; CA_SIN won't be detected
        self._engine.registry.add_recognizer(CaSinRecognizer())

    def detect(self, text: str) -> list[PiiSpan]:
        results = self._engine.analyze(text=text, entities=list(PII_ENTITIES), language="en")
        return [PiiSpan(r.start, r.end, r.entity_type, r.score) for r in results if r.score >= MIN_PII_SCORE]
