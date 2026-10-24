"""Pydantic схемы для API заявок (issue #7)."""

from pydantic import BaseModel, Field


class SubmitRequest(BaseModel):
    revision: int
    bki_consent_version: str = Field(..., min_length=1)


class ManagerDecisionRequest(BaseModel):
    revision: int
    action: str  # APPROVE, REJECT, COUNTER_OFFER, REQUEST_INFO
    amount_rub: int | None = None
    term_months: int | None = None
    comment: str | None = None


class OfferPreviewRequest(BaseModel):
    amount_rub: int
    term_months: int


class SignRequest(BaseModel):
    revision: int
    challenge_id: str
    code: str
