from pydantic import BaseModel, Field

from .common import MoneyStr
from .enums import ApplicationStatus, PurposeCode, TermsSource


class ClientApplicationView(BaseModel):
    id: str
    status: ApplicationStatus
    requested_amount_rub: MoneyStr
    term_months: int
    product_id: str
    purpose_code: PurposeCode
    terms_source: TermsSource


class ClientApplicationCreate(BaseModel):
    purpose_code: PurposeCode
    requested_amount_rub: int = Field(gt=0)
    term_months: int = Field(gt=0)
    product_id: str
    purpose_text: str = Field(max_length=2000)


# Ещкерее :)
