"""Structured-output schema. Every value is cited; wording is copied, never converted."""
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "contract-terms-v1"
_QUOTE = "Exact text copied from the cited element(s) that states this value; empty if not stated"
_IDS = "Ids of the <element> tags the quote comes from, e.g. [\"E12\"]"


class CitedText(BaseModel):
    value: str | None = Field(description="Copied verbatim from the contract; null if not stated")
    quote: str = Field(description=_QUOTE)
    element_ids: list[str] = Field(description=_IDS)


class CitedInt(BaseModel):
    value: int | None = Field(description="Null if not stated")
    quote: str = Field(description=_QUOTE)
    element_ids: list[str] = Field(description=_IDS)


class CitedFeeMethod(BaseModel):
    value: Literal["graduated", "cliff"] | None = Field(
        description="graduated: each band billed at its own rate ('first/next'); cliff: the whole value at one rate")
    quote: str = Field(description=_QUOTE)
    element_ids: list[str] = Field(description=_IDS)


class CitedCurrency(BaseModel):
    value: Literal["USD", "CAD"] | None
    quote: str = Field(description=_QUOTE)
    element_ids: list[str] = Field(description=_IDS)


class CitedFrequency(BaseModel):
    value: Literal["monthly", "quarterly", "annually"] | None
    quote: str = Field(description=_QUOTE)
    element_ids: list[str] = Field(description=_IDS)


class CitedTiming(BaseModel):
    value: Literal["arrears", "advance"] | None
    quote: str = Field(description=_QUOTE)
    element_ids: list[str] = Field(description=_IDS)


class FeeBandOut(BaseModel):
    band_text: str = Field(description="The band wording exactly as written, e.g. 'on the next $500 million'")
    rate_text: str = Field(description="The rate exactly as written, e.g. '0.45%'")
    quote: str = Field(description=_QUOTE)
    element_ids: list[str] = Field(description=_IDS)


class ContractTerms(BaseModel):
    fund_or_account: CitedText = Field(description="The fund or account the fee applies to")
    adviser: CitedText
    client: CitedText
    agreement_date: CitedText
    effective_date: CitedText
    fee_basis: CitedText = Field(description="What the fee is charged on, e.g. 'average daily net assets'")
    fee_method: CitedFeeMethod
    currency: CitedCurrency
    fee_bands: list[FeeBandOut] = Field(description="Every fee band in order, lowest band first")
    billing_frequency: CitedFrequency
    payment_timing: CitedTiming
    termination_notice_days: CitedInt
    governing_law: CitedText
    signatories: list[CitedText]
